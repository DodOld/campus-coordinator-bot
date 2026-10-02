"""Extensible schedule boundary; no dependency on any current Go service.

Integration TODO for the future Go-to-Python replacement:
1. authentication scheme and credential rotation;
2. endpoint(s) or event schema plus stable external identifiers;
3. authoritative timezone and daylight-saving policy;
4. recurrence, exception, cancellation, and update semantics;
5. pagination/sync cursor, idempotency keys, rate limits, error taxonomy, and SLA.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import aiohttp
import structlog
from dateutil.rrule import rrulestr
from icalendar import Calendar

log = structlog.get_logger(__name__)
TOMSK_TIMEZONE = ZoneInfo("Asia/Tomsk")
WEEKDAY_ARGUMENTS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5}


@dataclass(frozen=True, slots=True)
class ScheduleEvent:
    uid: str
    title: str
    starts_at: datetime
    ends_at: datetime
    description: str | None = None
    location: str | None = None


class ScheduleProvider(Protocol):
    async def events_for(self, target_date: date, timezone: tzinfo) -> list[ScheduleEvent]: ...

    async def today(self, timezone: tzinfo) -> list[ScheduleEvent]: ...

    async def tomorrow(self, timezone: tzinfo) -> list[ScheduleEvent]: ...


class ICalendarScheduleProvider:
    """Read RFC 5545 data from an HTTPS URL or local path and expand RRULEs."""

    def __init__(self, source: str, session: aiohttp.ClientSession | None = None) -> None:
        self.source = source
        self.session = session

    async def _calendar(self) -> Calendar:
        parsed = urlparse(self.source)
        if parsed.scheme in {"https", "http"}:
            if self.session is None:
                raise RuntimeError("an aiohttp session is required for URL calendars")
            async with self.session.get(self.source) as response:
                response.raise_for_status()
                content = await response.read()
        elif parsed.scheme in {"", "file"}:
            path = Path(parsed.path if parsed.scheme == "file" else self.source)
            content = await asyncio.to_thread(path.read_bytes)
        else:
            raise ValueError("schedule source must be an http(s) URL or local file")
        return Calendar.from_ical(content)

    async def events_for(self, target_date: date, timezone: tzinfo) -> list[ScheduleEvent]:
        calendar = await self._calendar()
        window_start = datetime.combine(target_date, time.min, timezone)
        window_end = window_start + timedelta(days=1)
        events: list[ScheduleEvent] = []
        for component in calendar.walk("VEVENT"):
            events.extend(_expand_component(component, window_start, window_end, timezone))
        return sorted(events, key=lambda event: event.starts_at)

    async def today(self, timezone: tzinfo) -> list[ScheduleEvent]:
        return await self.events_for(datetime.now(timezone).date(), timezone)

    async def tomorrow(self, timezone: tzinfo) -> list[ScheduleEvent]:
        return await self.events_for(datetime.now(timezone).date() + timedelta(days=1), timezone)


def _as_datetime(value: datetime | date, timezone: tzinfo) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone) if value.tzinfo is None else value
    return datetime.combine(value, time.min, timezone)


def _expand_component(component, window_start: datetime, window_end: datetime, timezone: tzinfo) -> list[ScheduleEvent]:
    starts_at = _as_datetime(component.decoded("DTSTART"), timezone)
    ends_at = _as_datetime(component.decoded("DTEND"), timezone) if component.get("DTEND") else starts_at
    duration = ends_at - starts_at
    recurrence = component.get("RRULE")
    if recurrence is None:
        occurrences = [starts_at]
    else:
        rule = rrulestr(recurrence.to_ical().decode(), dtstart=starts_at)
        occurrences = rule.between(window_start - duration, window_end, inc=True)
    raw_exdates = component.get("EXDATE")
    exdate_properties = raw_exdates if isinstance(raw_exdates, list) else [raw_exdates] if raw_exdates else []
    excluded = {_as_datetime(item.dt, timezone) for property_ in exdate_properties for item in property_.dts}
    result: list[ScheduleEvent] = []
    for occurrence in occurrences:
        occurrence = _as_datetime(occurrence, timezone).astimezone(timezone)
        event_end = occurrence + duration
        if occurrence in excluded or event_end <= window_start or occurrence >= window_end:
            continue
        result.append(
            ScheduleEvent(
                uid=str(component.get("UID", "")),
                title=str(component.get("SUMMARY", "Без названия")),
                starts_at=occurrence,
                ends_at=event_end,
                description=str(component.get("DESCRIPTION")) if component.get("DESCRIPTION") else None,
                location=str(component.get("LOCATION")) if component.get("LOCATION") else None,
            )
        )
    return result


@dataclass(frozen=True, slots=True)
class RenderedSchedule:
    message: str
    error: str | None = None


class GoBinaryScheduleProvider:
    """Run the checked-in 0B62 Go parser as a bounded JSON subprocess."""

    def __init__(self, binary_path: str, timeout_seconds: int) -> None:
        self.binary_path = binary_path
        self.timeout_seconds = timeout_seconds

    async def render_for(self, target_date: date) -> RenderedSchedule:
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                self.binary_path,
                "--json",
                "--date",
                target_date.isoformat(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=64 * 1024,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except FileNotFoundError:
            log.error("schedule_binary_not_found", binary_path=self.binary_path)
            return RenderedSchedule(message="", error="binary_not_found")
        except TimeoutError:
            if process is not None:
                process.kill()
                await process.wait()
            log.error("schedule_binary_timeout")
            return RenderedSchedule(message="", error="timeout")
        except OSError:
            log.exception("schedule_binary_start_failed")
            return RenderedSchedule(message="", error="startup_failed")

        if process.returncode != 0:
            log.error("schedule_binary_failed", returncode=process.returncode)
            return RenderedSchedule(message="", error="failed")
        try:
            payload = json.loads(stdout)
        except (TypeError, json.JSONDecodeError):
            log.error("schedule_binary_invalid_json")
            return RenderedSchedule(message="", error="invalid_json")
        if not isinstance(payload, dict) or not isinstance(payload.get("message"), str) or payload.get("error"):
            log.error("schedule_binary_invalid_payload")
            return RenderedSchedule(message="", error="invalid_payload")
        return RenderedSchedule(message=payload["message"])


def schedule_date_for_argument(argument: str | None, now: datetime | None = None) -> date:
    """Resolve today or the next requested class day in the Tomsk timezone."""
    current = (now or datetime.now(TOMSK_TIMEZONE)).astimezone(TOMSK_TIMEZONE).date()
    if argument is None:
        return current
    normalized = argument.casefold()
    if normalized == "sun":
        raise ValueError("Воскресенье не поддерживается: расписание доступно с mon по sat.")
    weekday = WEEKDAY_ARGUMENTS.get(normalized)
    if weekday is None:
        raise ValueError("Формат: !schedule [mon|tue|wed|thu|fri|sat]")
    return current + timedelta(days=(weekday - current.weekday()) % 7)
