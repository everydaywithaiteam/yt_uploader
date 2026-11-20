"""Scheduled-publish times: 'YYYY-MM-DD HH:MM', or just 'YYYY-MM-DD' for the config's default time."""
import datetime as dt
import sys
from zoneinfo import ZoneInfo

DEFAULT_TIME = "08:45"


def parse_local(value: str, tz_name: str, default_time: str = DEFAULT_TIME) -> dt.datetime:
    """Parse --publish-at into an aware local datetime; exit if malformed or in the past."""
    value = value.strip()
    if len(value) == 10:  # date only
        value = f"{value} {default_time}"
    try:
        local = dt.datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz_name))
    except ValueError:
        sys.exit(f"--publish-at {value!r}: use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'.")
    if local <= dt.datetime.now(local.tzinfo):
        sys.exit(f"--publish-at {value} is in the past.")
    return local


def add_days(local: dt.datetime, days: int) -> dt.datetime:
    """Add calendar days keeping the same wall-clock time across DST changes."""
    return (local.replace(tzinfo=None) + dt.timedelta(days=days)).replace(tzinfo=local.tzinfo)


def to_utc(local: dt.datetime) -> str:
    return local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def label(local: dt.datetime) -> str:
    return local.strftime("%a %Y-%m-%d %H:%M")
