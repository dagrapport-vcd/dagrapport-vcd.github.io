"""Leest client.config.json (de enige plek met klantspecifieke waarden).

Alle scripts in deze map importeren CFG hieruit. Het bestand staat in de
hoofdmap van de repo; het pad wordt vanaf dit bestand bepaald, dus het werkt
ongeacht de map waarvandaan een script wordt gestart.
"""
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'client.config.json')

with open(_PATH, encoding='utf-8') as _f:
    CFG = json.load(_f)

NAAM = CFG['naam']
DV = CFG['doorverwijzing']['naam']
STAFF_NAMES = [t['naam'] for t in CFG['team']]


def staff_by_local():
    """lokaal deel van het e-mailadres (alleen letters) -> naam"""
    out = {}
    for t in CFG['team']:
        local = ''.join(ch for ch in t['email'].split('@')[0].lower() if ch.isalpha())
        out[local] = t['naam']
    return out
