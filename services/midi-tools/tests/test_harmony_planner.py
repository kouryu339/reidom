from __future__ import annotations

import pytest
from reidom_midi_tools.chord_timeline import parse_chord_timeline
from reidom_midi_tools.harmony_planner import plan_piano_harmony
from reidom_midi_tools.music_copilot import Note, analyze_notes, normalize_notes, parse_chord


def _four_bar_melody() -> list[Note]:
    pitches = [64, 67, 69, 67, 65, 64, 62, 60, 64, 67, 72, 71, 69, 67, 62, 60]
    return [
        Note(
            note_id=index,
            pitch=pitch,
            start=float(index),
            length=0.8,
            velocity=90,
            channel=1,
        )
        for index, pitch in enumerate(pitches)
    ]


def test_extended_chord_vocabulary_supports_professional_colors() -> None:
    assert parse_chord("Cadd9")[1] == (0, 4, 7, 14)
    assert parse_chord("Dm9")[1] == (0, 3, 7, 10, 14)
    assert parse_chord("Bm7b5")[1] == (0, 3, 6, 10)
    assert parse_chord("A6")[1] == (0, 4, 7, 9)


def test_normalize_notes_uses_native_region_relative_position() -> None:
    notes = normalize_notes(
        {
            "notes": [
                {
                    "noteId": 8,
                    "note": 67,
                    "startRegionBeats": 9.5,
                    "startSourceBeats": 109.5,
                    "lengthBeats": 0.5,
                    "velocity": 80,
                    "channel": 1,
                }
            ]
        }
    )

    assert len(notes) == 1
    assert notes[0].start == 9.5
    assert notes[0].length == 0.5


def test_auto_key_penalizes_prominent_notes_outside_the_scale() -> None:
    pitches = (64, 67, 69, 67, 64, 60, 62, 65, 69, 67, 62, 67, 71, 72)
    starts = (0, 1.5, 2, 3, 4, 6, 7, 8, 9.5, 10, 12, 13, 14, 15)
    lengths = (1.5, 0.5, 1, 1, 2, 1, 1, 1.5, 0.5, 2, 1, 1, 1, 1)
    melody = [
        Note(index, pitch, start, length, 88, 1)
        for index, (pitch, start, length) in enumerate(zip(pitches, starts, lengths))
    ]

    plan = plan_piano_harmony(melody, style="pop", harmonic_rhythm="bar")

    assert plan["key"] == "C major"
    assert plan["bar_count"] == 4


def test_region_analysis_recognizes_sustained_colored_harmony() -> None:
    notes = [
        Note(index, pitch, 0.0, 4.0, 88, 1)
        for index, pitch in enumerate((60, 64, 67, 71))
    ]

    analysis = analyze_notes(notes)

    assert analysis["chords"] == [{"bar": 1, "chord": "Cmaj7"}]


def test_harmony_planner_is_deterministic_global_and_structurally_scored() -> None:
    first = plan_piano_harmony(
        _four_bar_melody(),
        style="ballad",
        complexity="balanced",
        harmonic_rhythm="bar",
    )
    second = plan_piano_harmony(
        _four_bar_melody(),
        style="ballad",
        complexity="balanced",
        harmonic_rhythm="bar",
    )

    assert first["key"] == "C major"
    assert first["progression"] == second["progression"]
    assert first["events"] == second["events"]
    assert len(first["progression"]) == 4
    timeline = parse_chord_timeline(first["timeline_text"])
    assert first["timeline_text"].startswith("4/4 @1:1-")
    assert first["timeline_text"].endswith(" || block")
    assert [chord.symbol for chord in timeline.chords] == [
        item["chord"] for item in first["progression"]
    ]
    assert [chord.duration for chord in timeline.chords] == [
        item["length_beats"] for item in first["progression"]
    ]
    assert first["progression"][-1]["degree"] == "I"
    assert first["quality"]["overall"] >= 60
    assert first["quality"]["evaluation_passes"] == 2
    assert first["quality"]["candidate_progressions_compared"] >= 8
    assert first["quality"]["audio_evaluated"] is False
    assert first["quality"]["average_voice_motion_semitones"] <= 5
    assert all(48 <= event["n"] <= 76 for event in first["events"])


def test_harmony_styles_change_vocabulary_rhythm_and_voicing() -> None:
    melody = _four_bar_melody()
    rock = plan_piano_harmony(
        melody,
        style="rock",
        complexity="balanced",
        harmonic_rhythm="bar",
    )
    jazz = plan_piano_harmony(
        melody,
        style="jazz",
        complexity="rich",
        harmonic_rhythm="bar",
    )

    rock_chords = [item["chord"] for item in rock["progression"]]
    jazz_chords = [item["chord"] for item in jazz["progression"]]
    assert rock_chords != jazz_chords
    assert any("7" in chord or "9" in chord for chord in jazz_chords)
    assert len(rock["events"]) != len(jazz["events"])
    assert rock["quality"]["style_fit"] >= 60
    assert jazz["quality"]["style_fit"] >= 60


def test_auto_harmonic_rhythm_uses_denser_changes_for_rnb() -> None:
    dense = [
        Note(index, 60 + index % 7, index * 0.5, 0.4, 84, 1)
        for index in range(32)
    ]
    plan = plan_piano_harmony(dense, style="rnb", complexity="rich")

    assert plan["harmonic_rhythm_beats"] == 2.0
    assert len(plan["progression"]) == 8


def test_harmony_planner_rejects_unsafe_or_unsupported_requests() -> None:
    melody = _four_bar_melody()

    with pytest.raises(ValueError, match="style must be"):
        plan_piano_harmony(melody, style="metalcore")
    with pytest.raises(ValueError, match="at least two notes"):
        plan_piano_harmony(melody[:1])
    with pytest.raises(ValueError, match="span at least one octave"):
        plan_piano_harmony(melody, low_pitch=60, high_pitch=68)
