from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone, tzinfo


def get_day_tz(ref_dt: datetime, default_offset_hours: int = 5) -> tzinfo:
    if ref_dt.tzinfo is not None:
        return ref_dt.tzinfo
    return timezone(timedelta(hours=default_offset_hours))


def norm_dt(dt: datetime, tz: tzinfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz, microsecond=0)
    return dt.astimezone(tz).replace(microsecond=0)


def local_hhmm_to_dt(day_date: date_type, hhmm: str, tz: tzinfo) -> datetime:
    hh, mm = map(int, hhmm.split(":"))
    return datetime.combine(day_date, time(hour=hh, minute=mm, second=0), tzinfo=tz)


def dt_to_sec(dt: datetime, origin: datetime) -> int:
    return int(round((dt - origin).total_seconds()))


def sec_to_dt(sec: int, origin: datetime, tz: tzinfo) -> datetime:
    return (origin + timedelta(seconds=int(sec))).astimezone(tz).replace(microsecond=0)
