from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Any

PITCH_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
ROOTS = {
    "C": 0, "B#": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3,
    "E": 4, "FB": 4, "E#": 5, "F": 5, "F#": 6, "GB": 6, "G": 7,
    "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11, "CB": 11,
}
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


@dataclass(frozen=True)
class Note:
    note_id: str | int
    pitch: int
    start: float
    length: float
    velocity: int
    channel: int


def normalize_notes(raw: dict[str, Any] | list[Any]) -> list[Note]:
    items = raw.get("notes", []) if isinstance(raw, dict) else raw
    notes: list[Note] = []
    for index, item in enumerate(items if isinstance(items, list) else []):
        if not isinstance(item, dict):
            continue
        try:
            notes.append(
                Note(
                    note_id=str(_first(item, "note_id", "noteId", "id", default=index)),
                    pitch=int(_first(item, "note", "pitch")),
                    start=float(
                        _first(
                            item,
                            "startRegionBeats",
                            "startBeats",
                            "regionBeat",
                            "startSourceBeats",
                            "start",
                            "beat",
                            default=0.0,
                        )
                    ),
                    length=float(_first(item, "lengthBeats", "durationBeats", "length", "duration", default=0.25)),
                    velocity=int(_first(item, "velocity", default=96)),
                    channel=int(_first(item, "channel", default=1)),
                )
            )
        except (TypeError, ValueError):
            continue
    return sorted(notes, key=lambda note: (note.start, note.pitch, note.note_id))


def analyze_notes(notes: list[Note], beats_per_bar: float = 4.0) -> dict[str, Any]:
    if not notes:
        return {"note_count": 0, "estimated_key": "unknown", "chords": [], "phrase_blocks": []}

    key = _estimate_key(notes)
    end = max(note.start + note.length for note in notes)
    bar_count = max(1, int((max(end, 0.001) - 0.001) // beats_per_bar) + 1)
    chords = []
    phrase_blocks = []
    for bar in range(bar_count):
        window = [
            note
            for note in notes
            if note.start < (bar + 1) * beats_per_bar
            and note.start + note.length > bar * beats_per_bar
        ]
        if window:
            chords.append({"bar": bar + 1, "chord": _estimate_chord(window)})
    for first_bar in range(0, bar_count, 4):
        window = [
            note for note in notes
            if first_bar * beats_per_bar <= note.start < min(first_bar + 4, bar_count) * beats_per_bar
        ]
        density = len(window) / max(1.0, min(4, bar_count - first_bar) * beats_per_bar)
        phrase_blocks.append(
            {
                "bars": f"{first_bar + 1}-{min(first_bar + 4, bar_count)}",
                "activity": _density_label(density),
                "note_count": len(window),
            }
        )

    starts = Counter(round(note.start, 4) for note in notes)
    simultaneous = sum(1 for count in starts.values() if count > 1)
    density = len(notes) / max(end, beats_per_bar)
    poly_ratio = simultaneous / max(1, len(starts))
    texture = "polyphonic" if poly_ratio >= 0.25 else "monophonic"
    if density < 0.75:
        texture = f"sparse {texture}"
    elif density >= 3.0:
        texture = f"dense {texture}"

    pitches = [note.pitch for note in notes]
    center = float(median(pitches))
    role = _role(center, density, poly_ratio)
    return {
        "note_count": len(notes),
        "bar_count": bar_count,
        "pitch_range": {"low": min(pitches), "high": max(pitches), "center": round(center, 1)},
        "estimated_key": key,
        "chords": chords,
        "texture": texture,
        "suggested_role": role,
        "phrase_blocks": phrase_blocks,
    }


def humanize_edits(
    notes: list[Note], timing_amount_beats: float, velocity_amount: int, seed: int
) -> list[dict[str, Any]]:
    edits: list[dict[str, Any]] = []
    for note in notes:
        rng = random.Random(f"{seed}:{note.note_id}:{note.pitch}:{note.start}")
        timing = rng.uniform(-timing_amount_beats, timing_amount_beats)
        timing = max(-note.start, timing)
        velocity = max(1, min(127, note.velocity + rng.randint(-velocity_amount, velocity_amount)))
        edit: dict[str, Any] = {"note_id": str(note.note_id)}
        if timing_amount_beats > 0:
            edit["delta_beats"] = round(timing, 5)
        if velocity_amount > 0:
            edit["velocity"] = velocity
        edits.append(edit)
    return edits


def drum_events(style: str, bars: int, velocity: int, beats_per_bar: int = 4) -> list[dict[str, Any]]:
    patterns = {
        "backbeat": ((36, (1.0, 3.0)), (38, (2.0, 4.0)), (42, (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5))),
        "four_on_floor": ((36, (1.0, 2.0, 3.0, 4.0)), (38, (2.0, 4.0)), (42, (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5))),
        "half_time": ((36, (1.0, 3.5)), (38, (3.0,)), (42, (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5))),
    }
    if style not in patterns:
        raise ValueError("style must be backbeat, four_on_floor, or half_time")
    events = []
    for bar in range(1, bars + 1):
        for pitch, beats in patterns[style]:
            for beat in beats:
                accent = 8 if pitch == 38 else (4 if beat in (1.0, 3.0) else 0)
                events.append(_event(bar, beat, pitch, min(127, velocity + accent), 0.2, 10))
    return events


def bass_events(chords: list[str], beats_per_chord: float, style: str, octave: int) -> list[dict[str, Any]]:
    if style not in {"roots", "eighths", "root_fifth"}:
        raise ValueError("style must be roots, eighths, or root_fifth")
    events: list[dict[str, Any]] = []
    cursor = 0.0
    for symbol in chords:
        root, intervals = parse_chord(symbol)
        root_pitch = max(0, min(127, 12 * (octave + 1) + root))
        step = 0.5 if style == "eighths" else (beats_per_chord / 2 if style == "root_fifth" else beats_per_chord)
        positions = [i * step for i in range(max(1, int(beats_per_chord / step)))]
        for index, offset in enumerate(positions):
            pitch = root_pitch
            if style == "root_fifth" and index % 2:
                pitch = min(127, root_pitch + (7 if 7 in intervals else intervals[-1]))
            events.append(_event_at_offset(cursor + offset, pitch, 94 if index == 0 else 84, min(step * 0.9, 1.0), 1))
        cursor += beats_per_chord
    return events


def accompaniment_events(
    chords: list[str], beats_per_chord: float, rhythm: str, octave: int
) -> list[dict[str, Any]]:
    if rhythm not in {"block", "half", "quarters"}:
        raise ValueError("rhythm must be block, half, or quarters")
    events: list[dict[str, Any]] = []
    cursor = 0.0
    for symbol in chords:
        root, intervals = parse_chord(symbol)
        base = 12 * (octave + 1) + root
        pitches = [max(0, min(127, base + interval)) for interval in intervals]
        step = {"block": beats_per_chord, "half": 2.0, "quarters": 1.0}[rhythm]
        positions = [i * step for i in range(max(1, int(beats_per_chord / step)))]
        for offset in positions:
            for pitch in pitches:
                events.append(_event_at_offset(cursor + offset, pitch, 78, min(step * 0.9, beats_per_chord), 1))
        cursor += beats_per_chord
    return events


def parse_chord(symbol: str) -> tuple[int, tuple[int, ...]]:
    match = re.fullmatch(r"\s*([A-Ga-g])([#b]?)(.*)\s*", symbol)
    if not match:
        raise ValueError(f"unsupported chord: {symbol}")
    root_name = (match.group(1).upper() + match.group(2)).upper()
    quality = match.group(3).strip().lower()
    root = ROOTS[root_name]
    if quality in ("", "maj"):
        intervals = (0, 4, 7)
    elif quality in ("m", "min"):
        intervals = (0, 3, 7)
    elif quality == "7":
        intervals = (0, 4, 7, 10)
    elif quality in ("maj7", "ma7"):
        intervals = (0, 4, 7, 11)
    elif quality in ("m7", "min7"):
        intervals = (0, 3, 7, 10)
    elif quality == "m7b5":
        intervals = (0, 3, 6, 10)
    elif quality in ("dim", "dim7"):
        intervals = (0, 3, 6) if quality == "dim" else (0, 3, 6, 9)
    elif quality == "aug":
        intervals = (0, 4, 8)
    elif quality == "sus2":
        intervals = (0, 2, 7)
    elif quality == "sus4":
        intervals = (0, 5, 7)
    elif quality == "add9":
        intervals = (0, 4, 7, 14)
    elif quality == "6":
        intervals = (0, 4, 7, 9)
    elif quality == "m6":
        intervals = (0, 3, 7, 9)
    elif quality == "9":
        intervals = (0, 4, 7, 10, 14)
    elif quality == "m9":
        intervals = (0, 3, 7, 10, 14)
    else:
        raise ValueError(f"unsupported chord quality: {symbol}")
    return root, intervals


def midi_payload(events: list[dict[str, Any]], is_drum: bool = False) -> dict[str, Any]:
    return {
        "channel_base": "one",
        "channel": 10 if is_drum else 1,
        "is_drum_mode": is_drum,
        "ticks_per_quarter": 960,
        "time_signature": "4/4",
        "midi_events": events,
    }


def _first(item: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return default


def _estimate_key(notes: list[Note]) -> str:
    weights = [0.0] * 12
    for note in notes:
        weights[note.pitch % 12] += max(0.1, min(note.length, 4.0))
    best = (-1.0, "unknown")
    for root in range(12):
        for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            score = sum(weights[pitch] * profile[(pitch - root) % 12] for pitch in range(12))
            if score > best[0]:
                best = (score, f"{PITCH_NAMES[root]} {mode}")
    return best[1]


def _estimate_chord(notes: list[Note]) -> str:
    weights: Counter[int] = Counter()
    for note in notes:
        beat = note.start % 4.0
        accent = 1.5 if abs(beat) <= 0.06 else (1.2 if abs(beat - 2.0) <= 0.06 else 1.0)
        weights[note.pitch % 12] += max(0.15, min(note.length, 4.0)) * accent

    candidates = (
        ("", (0, 4, 7)),
        ("m", (0, 3, 7)),
        ("7", (0, 4, 7, 10)),
        ("maj7", (0, 4, 7, 11)),
        ("m7", (0, 3, 7, 10)),
        ("dim", (0, 3, 6)),
        ("m7b5", (0, 3, 6, 10)),
        ("sus2", (0, 2, 7)),
        ("sus4", (0, 5, 7)),
    )
    best = (-999.0, "unknown")
    for root in range(12):
        for suffix, intervals in candidates:
            chord = {(root + interval) % 12 for interval in intervals}
            score = 3.0 * sum(weight for pitch, weight in weights.items() if pitch in chord)
            score -= 1.8 * sum(
                1.0 if index < 3 else 0.45
                for index, interval in enumerate(intervals)
                if (root + interval) % 12 not in weights
            )
            for pitch, weight in weights.items():
                if pitch in chord:
                    continue
                interval = (pitch - root) % 12
                score += (0.25 if interval in {2, 5, 9} else -1.0) * weight
            if root in weights:
                score += min(1.2, weights[root] * 0.25)
            score -= max(0, len(intervals) - 3) * 0.2
            if score > best[0]:
                best = (score, f"{PITCH_NAMES[root]}{suffix}")
    return best[1]


def _role(center: float, density: float, poly_ratio: float) -> str:
    if center < 50:
        return "bass"
    if poly_ratio >= 0.35 and density >= 1.0:
        return "harmony or pad"
    if density >= 2.5:
        return "rhythmic accompaniment"
    if center >= 67:
        return "lead or melody"
    return "inner voice or accompaniment"


def _density_label(density: float) -> str:
    if density < 0.75:
        return "low"
    if density < 2.0:
        return "medium"
    return "high"


def _event_at_offset(offset: float, pitch: int, velocity: int, length: float, channel: int) -> dict[str, Any]:
    bar = int(offset // 4.0) + 1
    beat = round(offset % 4.0 + 1.0, 5)
    return _event(bar, beat, pitch, velocity, length, channel)


def _event(bar: int, beat: float, pitch: int, velocity: int, length: float, channel: int) -> dict[str, Any]:
    return {"bar": bar, "b": beat, "t": 0, "n": pitch, "v": velocity, "l": length, "channel": channel}
