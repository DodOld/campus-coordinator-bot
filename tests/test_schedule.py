from datetime import date
from zoneinfo import ZoneInfo

import pytest

from app.schedule import ICalendarScheduleProvider


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
