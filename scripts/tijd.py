"""Amsterdamse tijd, met zomer- en wintertijd.

De scripts rekenden met een vaste +2 uur (zomertijd). Sinds de overgang naar wintertijd (25 okt 2026)
stonden alle tijden daardoor een uur te laat. Dit is de enige plek waar de tijdzone wordt bepaald.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_AMS = ZoneInfo('Europe/Amsterdam')


def ams_offset(dt_utc):
    """Verschil tussen Amsterdamse tijd en UTC op dat moment (1 of 2 uur)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(_AMS).utcoffset()


def ams_nu():
    """Nu, als Amsterdamse kloktijd (zonder tijdzone-info)."""
    nu = datetime.now(timezone.utc)
    return (nu + ams_offset(nu)).replace(tzinfo=None)
