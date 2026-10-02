"""Вызов Go-бинарника для получения расписания."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)

# Путь к бинарнику — настраивается через env
GO_BINARY = "schedule-bot"


@dataclass
class ScheduleResult:
    message: str
    first_lesson: str | None = None
    error: str | None = None


async def fetch_schedule_json(
    binary_path: str = GO_BINARY,
    timeout: float = 60.0,
) -> ScheduleResult:
    """
    Запускает Go-бинарник в JSON-режиме и возвращает результат.

    Args:
        binary_path: путь к скомпилированному Go-бинарнику
        timeout: таймаут в секундах

    Returns:
        ScheduleResult с расписанием или ошибкой
    """
    cmd = [binary_path, "--json"]

    log.info("go_schedule_start", cmd=cmd)

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.wait()
        log.error("go_schedule_timeout", timeout=timeout)
        return ScheduleResult(message="", error="Таймаут получения расписания")
    except FileNotFoundError:
        log.error("go_binary_not_found", path=binary_path)
        return ScheduleResult(message="", error="Go-бинарник не найден")

    if proc.returncode != 0:
        log.error("go_schedule_failed", returncode=proc.returncode,
                  stderr=stderr.decode()[:500])
        return ScheduleResult(message="", error="Ошибка получения расписания")

    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        log.error("go_schedule_bad_json", raw=stdout.decode()[:500], err=str(e))
        return ScheduleResult(message="", error="Некорректный ответ от Go")

    if data.get("error"):
        return ScheduleResult(message="", error=data["error"])

    return ScheduleResult(
        message=data.get("message", ""),
        first_lesson=data.get("first_lesson"),
    )
