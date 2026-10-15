from __future__ import annotations

import pytest
from reidom_midi_tools.chord_timeline import (
    build_chord_timeline,
    format_chord_timeline,
    parse_chord_timeline,
)

TRANSITION_TIMELINE = (
    "4/4 @1:1-5:1 | "
    "Am7(3) C7/E(1) Fmaj7(3) D7/F#(1) G7(3) G7/B(1) Cadd9(4) "
    "|| arp(up, rate=1/8, oct=2, gate=0.85)"
)


def test_timeline_parses_positions_durations_and_transition_chords() -> None:
    plan = build_chord_timeline(TRANSITION_TIMELINE)

    assert plan["range"] == {
        "start": "1:1",
        "end": "5:1",
        "length_beats": 16.0,
    }
    assert [item["start"] for item in plan["chords"]] == [
        "1:1",
        "1:4",
        "2:1",
        "2:4",
        "3:1",
        "3:4",
        "4:1",
    ]
    assert [item["end"] for item in plan["chords"]] == [
        "1:4",
        "2:1",
        "2:4",
        "3:1",
        "3:4",
        "4:1",
        "5:1",
    ]
    assert plan["short_chord_count"] == 3
    assert len(plan["events"]) == 32
    assert plan["timeline_text"] == TRANSITION_TIMELINE


def test_slash_chords_force_the_requested_lowest_pitch_class() -> None:
    plan = build_chord_timeline(TRANSITION_TIMELINE)
    voicings = {
        item["symbol"]: item["voicing"]
        for item in plan["chords"]
        if "/" in item["symbol"]
    }

    assert voicings["C7/E"][0] % 12 == 4
    assert voicings["D7/F#"][0] % 12 == 6
    assert voicings["G7/B"][0] % 12 == 11


def test_local_performance_override_inherits_global_arp_values() -> None:
    timeline = parse_chord_timeline(
        "4/4 @1:1-2:1 | C(2){arp(down)} G7(2) "
        "|| arp(up, rate=1/8, oct=2, gate=0.8)"
    )
    first, second = timeline.chords

    assert first.performance.direction == "down"
    assert first.performance.rate_text == "1/8"
    assert first.performance.octaves == 2
    assert second.performance.direction == "up"
    assert "{arp(down, rate=1/8, oct=2, gate=0.8)}" in format_chord_timeline(
        timeline
    )


def test_random_arpeggio_is_deterministic_for_the_same_seed() -> None:
    text = (
        "4/4 @1:1-2:1 | Cmaj7(4) "
        "|| arp(random, rate=1/16, oct=2, gate=0.8, seed=42)"
    )

    first = build_chord_timeline(text)
    second = build_chord_timeline(text)

    assert first["events"] == second["events"]
    assert len(first["events"]) == 16


def test_timeline_accepts_full_width_duration_parentheses() -> None:
    timeline = parse_chord_timeline(
        "4/4 @1:1-2:1 | Am7（1） Fmaj7（1） G7（1） Cadd9（1） || block"
    )

    assert [chord.duration for chord in timeline.chords] == [1.0, 1.0, 1.0, 1.0]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "4/4 @1:1-5:1 | Am7(4) Fmaj7(4) G7(4) || block",
            "durations total 12 beats",
        ),
        (
            "3/4 @1:1-2:1 | C(3) || block",
            "currently supports 4/4 only",
        ),
        (
            "4/4 @1:1-2:1 | H7(4) || block",
            "unsupported timeline text",
        ),
        (
            "4/4 @1:1-2:1 | C(4) || arp(sideways, rate=1/8)",
            "arp direction must be one of",
        ),
    ],
)
def test_timeline_rejects_ambiguous_or_unsafe_text(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_chord_timeline(text)
