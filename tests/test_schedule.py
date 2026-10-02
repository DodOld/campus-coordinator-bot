from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.repositories import BotRepository
from app.schedule import GoBinaryScheduleProvider, ICalendarScheduleProvider, schedule_date_for_argument
from app.schedule_service import seconds_until_tomsk_midnight


@pytest.mark.asyncio
async def test_icalendar_expands_daily_recurrence(tmp_path) -> None:
    calendar = tmp_path / "events.ics"
    calendar.write_text(
        """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:daily-1
DTSTART:20260930T090000Z
DTEND:20260930T100000Z
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:Standup
END:VEVENT
END:VCALENDAR
"""
    )
    provider = ICalendarScheduleProvider(str(calendar))

    events = await provider.events_for(date(2026, 10, 1), ZoneInfo("Europe/Moscow"))

    assert len(events) == 1
    assert events[0].title == "Standup"
    assert events[0].starts_at.hour == 12


def test_schedule_day_arguments_use_tomsk_and_exclude_sunday() -> None:
    now = datetime(2026, 10, 5, 12, tzinfo=ZoneInfo("Asia/Tomsk"))  # Monday

    assert schedule_date_for_argument(None, now) == date(2026, 10, 5)
    assert schedule_date_for_argument("wed", now) == date(2026, 10, 7)
    assert schedule_date_for_argument("mon", now) == date(2026, 10, 5)
    with pytest.raises(ValueError, match="Воскресенье"):
        schedule_date_for_argument("sun", now)


def test_next_tomsk_midnight_is_calculated_in_tomsk_timezone() -> None:
    now = datetime(2026, 10, 5, 23, 59, 30, tzinfo=ZoneInfo("Asia/Tomsk"))

    assert seconds_until_tomsk_midnight(now) == 30


@pytest.mark.asyncio
async def test_go_provider_passes_date_and_accepts_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[str] = []

    class Process:
        returncode = 0

        async def communicate(self):
            return '{"message":"Расписание"}'.encode(), b""

    async def create(*args, **kwargs):
        received.extend(args)
        return Process()

    monkeypatch.setattr("app.schedule.asyncio.create_subprocess_exec", create)
    result = await GoBinaryScheduleProvider("/bin/schedule", 5).render_for(date(2026, 10, 5))

    assert received == ["/bin/schedule", "--json", "--date", "2026-10-05"]
    assert result.message == "Расписание"
    assert result.error is None


@pytest.mark.asyncio
async def test_go_provider_hides_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class Process:
        returncode = 0

        async def communicate(self):
            return b"not-json", b"sensitive details"

    async def create(*args, **kwargs):
        return Process()

    monkeypatch.setattr("app.schedule.asyncio.create_subprocess_exec", create)
    result = await GoBinaryScheduleProvider("/bin/schedule", 5).render_for(date(2026, 10, 5))

    assert result.message == ""
    assert result.error == "invalid_json"


@pytest.mark.asyncio
async def test_daily_schedule_claim_is_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        claim = await BotRepository(session).claim_schedule_publication(-1001, date(2026, 10, 5))
        assert claim is not None
        await session.commit()
    async with sessions() as session:
        duplicate = await BotRepository(session).claim_schedule_publication(-1001, date(2026, 10, 5))
        assert duplicate is None
        await session.commit()
    await engine.dispose()
