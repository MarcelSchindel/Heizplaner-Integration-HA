"""Reine Plan-Logik ohne Home-Assistant-Abhängigkeit (testbar)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re

from .const import (
    DAYTYPES,
    PLAN_STUFEN,
    ST_NACHT,
    TT_BUERO,
    TT_HOMEOFFICE,
    TT_WOCHENENDE,
    WEEKDAYS,
)

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class PlanError(ValueError):
    """Ungültiger Plan."""


def parse_time(value: str) -> int:
    """'HH:MM' -> Minuten seit Mitternacht."""
    m = _TIME_RE.match(str(value).strip())
    if not m:
        raise PlanError(f"Ungültige Uhrzeit: {value!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


def fmt_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def normalize_points(points: list) -> list[list[str]]:
    """Prüft und sortiert Wechselpunkte [["HH:MM", stufe], ...]."""
    if not isinstance(points, list) or not points:
        raise PlanError("Ein Plan braucht mindestens einen Wechselpunkt")
    seen: dict[int, str] = {}
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise PlanError(f"Ungültiger Wechselpunkt: {p!r}")
        minute = parse_time(p[0])
        stufe = str(p[1])
        if stufe not in PLAN_STUFEN:
            raise PlanError(f"Unbekannte Stufe: {stufe!r}")
        if minute in seen:
            raise PlanError(f"Uhrzeit doppelt: {fmt_time(minute)}")
        seen[minute] = stufe
    return [[fmt_time(m), seen[m]] for m in sorted(seen)]


def _sorted(points: list) -> list[tuple[int, str]]:
    return sorted((parse_time(t), s) for t, s in points)


def normalize_room_plan(plan: dict, defaults: dict) -> dict:
    """Ergänzt fehlende Tagtypen eines Raums mit Standardwerten."""
    out = {}
    for tt in DAYTYPES:
        try:
            out[tt] = normalize_points(plan.get(tt)) if plan and plan.get(tt) else normalize_points(defaults[tt])
        except PlanError:
            out[tt] = normalize_points(defaults[tt])
    return out


@dataclass
class DayInfo:
    """Welcher Tagtyp gilt an einem Tag und warum."""

    daytype: str
    reason: str  # "wochentag" | "feiertag" | "frei" | "homeoffice"
    holiday: str | None = None


def base_daytype(
    day: date,
    buero_days: list[str],
    homeoffice_days: list[str],
    holiday_name: str | None,
) -> DayInfo:
    """Tagtyp nur aus Wochentag + Feiertag (ohne Schalter)."""
    if holiday_name:
        return DayInfo(TT_WOCHENENDE, "feiertag", holiday_name)
    wd = WEEKDAYS[day.weekday()]
    if wd in buero_days:
        return DayInfo(TT_BUERO, "wochentag")
    if wd in homeoffice_days:
        return DayInfo(TT_HOMEOFFICE, "wochentag")
    return DayInfo(TT_WOCHENENDE, "wochentag")


def effective_daytype(base: DayInfo, frei: bool, homeoffice: bool) -> DayInfo:
    """Schalter anwenden: Frei > Homeoffice > Wochentag/Feiertag."""
    if base.daytype == TT_WOCHENENDE:
        return base
    if frei:
        return DayInfo(TT_WOCHENENDE, "frei")
    if homeoffice and base.daytype == TT_BUERO:
        return DayInfo(TT_HOMEOFFICE, "homeoffice")
    return base


@dataclass
class PlanState:
    """Aktuelle Stufe eines Raums laut Plan."""

    stufe: str
    since: str | None  # Uhrzeit des letzten Wechsels heute (None = seit gestern)
    next_time: str | None  # nächster Wechsel heute
    next_stufe: str | None


def stufe_at(today_points: list, yesterday_points: list | None, minute: int) -> PlanState:
    """Stufe zu einer Uhrzeit. Vor dem ersten Wechsel gilt die letzte Stufe von gestern."""
    today = _sorted(today_points)
    current: str | None = None
    since: str | None = None
    nxt: tuple[int, str] | None = None
    for t, s in today:
        if t <= minute:
            current, since = s, fmt_time(t)
        elif nxt is None:
            nxt = (t, s)
    if current is None:
        prev = _sorted(yesterday_points) if yesterday_points else today
        current = prev[-1][1] if prev else ST_NACHT
    # Wechsel auf die gleiche Stufe ist kein Wechsel -> den nächsten echten suchen
    if nxt is not None and nxt[1] == current:
        later = [(t, s) for t, s in today if t > nxt[0] and s != current]
        nxt = later[0] if later else None
    return PlanState(
        stufe=current,
        since=since,
        next_time=fmt_time(nxt[0]) if nxt else None,
        next_stufe=nxt[1] if nxt else None,
    )


def minute_of(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def yesterday(d: date) -> date:
    return d - timedelta(days=1)
