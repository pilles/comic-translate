"""Cas de banc par défaut pour tools/bench_translation.py.

Phrases inventées, reprises du banc `test_traduction.py` écrit le
2026-09-11 (dialogue, argot, MAJUSCULES, onomatopées, fautes d'OCR, page de
8 bulles). Aucune page de BD réelle : cf. specs/00-feuille-de-route.md §6.3.
"""

from __future__ import annotations

from typing import TypedDict


class BenchCase(TypedDict, total=False):
    name: str
    blocks: list[str]
    allow_unchanged: list[int] | bool


DEFAULT_CASES: list[BenchCase] = [
    {
        "name": "Dialogue simple",
        "blocks": [
            "Where were you last night?",
            "I told you, I was at the lab.",
            "You're lying to me.",
        ],
    },
    {
        "name": "Familier / argot",
        "blocks": [
            "Dude, that was totally epic!",
            "No way I'm going back in there.",
            "Chill out, man.",
        ],
    },
    {
        "name": "MAJUSCULES BD",
        "blocks": [
            "WHAT ARE YOU DOING HERE?!",
            "GET DOWN! THEY'RE COMING!",
            "I KNEW IT...",
        ],
    },
    {
        "name": "Onomatopées",
        "blocks": ["KRAKOOM!", "#@$%!", "Huh?", "BLAM! BLAM!"],
        "allow_unchanged": True,
    },
    {
        "name": "Fautes d'OCR",
        "blocks": [
            "I CAN'T BELIEVE Y0U DID THAT",
            "HOLD 0N, I'M C0MING",
            "WAIT FOR ME-- PLEASE",
        ],
    },
    {
        "name": "Page complète (8 bulles)",
        "blocks": [
            "Captain, the engines are failing!",
            "Then reroute power from the shields.",
            "That's suicide, sir!",
            "We don't have a choice.",
            "BOOM!",
            "Everyone, hold on tight!",
            "I've got a bad feeling about this...",
            "Too late for that now.",
        ],
    },
]
