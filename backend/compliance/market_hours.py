"""US equity regular-session helpers.

Uses America/New_York time and a curated NYSE holiday list.
Early closes end at 13:00 ET on known half-days.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Full-day NYSE holidays (observed dates). Extend yearly as needed.
# Source pattern: standard NYSE observed holidays - free, hardcoded.
_NYSE_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1),
    date(2025, 1, 20),
    date(2025, 2, 17),
    date(2025, 4, 18),
    date(2025, 5, 26),
    date(2025, 6, 19),
    date(2025, 7, 4),
    date(2025, 9, 1),
    date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),  # Independence Day observed
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
    # 2027
    date(2027, 1, 1),
    date(2027, 1, 18),
    date(2027, 2, 15),
    date(2027, 3, 26),
    date(2027, 5, 31),
    date(2027, 6, 18),
    date(2027, 7, 5),  # Independence Day observed
    date(2027, 9, 6),
    date(2027, 11, 25),
    date(2027, 12, 24),  # Christmas observed
}

# Early close 13:00 ET (day before Independence Day / Thanksgiving / Christmas patterns)
_EARLY_CLOSE: dict[date, time] = {
    date(2025, 7, 3): time(13, 0),
    date(2025, 11, 28): time(13, 0),
    date(2025, 12, 24): time(13, 0),
    date(2026, 11, 27): time(13, 0),
    date(2026, 12, 24): time(13, 0),
    date(2027, 11, 26): time(13, 0),
}

RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


def now_et(now: datetime | None = None) -> datetime:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(ET)


def session_status(
    *,
    now: datetime | None = None,
    allow_extended_hours: bool = False,
) -> dict[str, Any]:
    """Return whether US equity regular session is open for new market orders."""
    et = now_et(now)
    d = et.date()
    t = et.time()
    weekday = et.weekday()  # Mon=0

    reasons: list[str] = []
    if weekday >= 5:
        reasons.append("Weekend - regular session closed.")
    if d in _NYSE_HOLIDAYS:
        reasons.append(f"NYSE holiday ({d.isoformat()}).")

    open_t = RTH_OPEN
    close_t = _EARLY_CLOSE.get(d, RTH_CLOSE)

    in_rth = (
        weekday < 5
        and d not in _NYSE_HOLIDAYS
        and open_t <= t < close_t
    )

    # Extended hours (pre 4:00-9:30 / post 16:00-20:00) - never default on.
    pre = time(4, 0) <= t < open_t
    post = close_t <= t < time(20, 0)
    in_extended = weekday < 5 and d not in _NYSE_HOLIDAYS and (pre or post)

    if in_rth:
        open_for_orders = True
        phase = "regular"
    elif allow_extended_hours and in_extended:
        open_for_orders = True
        phase = "extended"
        reasons.append("Extended hours allowed by config.")
    else:
        open_for_orders = False
        phase = "closed"
        if not reasons:
            if in_extended:
                reasons.append(
                    "Outside regular hours; extended-hours trading is disabled."
                )
            else:
                reasons.append("Outside US equity trading hours.")

    next_hint = None
    if not open_for_orders and weekday < 5 and d not in _NYSE_HOLIDAYS and t < open_t:
        next_hint = f"Regular session opens {d.isoformat()} {open_t.isoformat()} ET"
    elif not open_for_orders:
        next_hint = "Next regular session: next NYSE business day 09:30 ET"

    return {
        "open_for_market_orders": open_for_orders,
        "phase": phase,
        "timezone": "America/New_York",
        "local_et": et.isoformat(),
        "session_date": d.isoformat(),
        "regular_open": open_t.isoformat(),
        "regular_close": close_t.isoformat(),
        "allow_extended_hours": allow_extended_hours,
        "reasons": reasons,
        "next_hint": next_hint,
        "note": (
            "Clock is America/New_York (not local PC timezone). "
            "Holiday list is curated and free - verify around holiday weeks."
        ),
    }
