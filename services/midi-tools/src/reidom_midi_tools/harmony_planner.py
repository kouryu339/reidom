from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise
from math import ceil, exp
from statistics import median
from typing import Any

from .chord_timeline import timeline_text_from_progression
from .music_copilot import PITCH_NAMES, ROOTS, Note, parse_chord

SUPPORTED_HARMONY_STYLES = ("pop", "ballad", "rock", "rnb", "jazz", "cinematic")
SUPPORTED_COMPLEXITIES = ("simple", "balanced", "rich")
SUPPORTED_HARMONIC_RHYTHMS = ("auto", "half_bar", "bar", "two_bars")

_SCALE_INTERVALS = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
}
_FUNCTION_TRANSITIONS = {
    ("tonic", "tonic"): 0.1,
    ("tonic", "predominant"): 1.0,
    ("tonic", "dominant"): 0.7,
    ("predominant", "tonic"): 0.0,
    ("predominant", "predominant"): -0.2,
    ("predominant", "dominant"): 1.5,
    ("dominant", "tonic"): 2.0,
    ("dominant", "predominant"): -0.8,
    ("dominant", "dominant"): -0.1,
}
_STYLE_TRANSITIONS = {
    "pop": {
        ("I", "V"): 1.1,
        ("V", "vi"): 1.0,
        ("vi", "IV"): 1.1,
        ("IV", "I"): 0.8,
        ("IV", "V"): 0.8,
        ("I", "vi"): 0.7,
    },
    "ballad": {
        ("I", "iii"): 0.8,
        ("iii", "vi"): 0.8,
        ("vi", "IV"): 0.9,
        ("IV", "ii"): 0.7,
        ("ii", "V"): 1.2,
        ("V", "I"): 1.3,
    },
    "rock": {
        ("I", "bVII"): 1.2,
        ("bVII", "IV"): 1.0,
        ("IV", "I"): 1.0,
        ("I", "V"): 0.8,
        ("V", "IV"): 0.6,
    },
    "rnb": {
        ("I", "vi"): 0.9,
        ("vi", "ii"): 1.0,
        ("ii", "V"): 1.3,
        ("V", "I"): 1.4,
        ("IV", "iii"): 0.8,
        ("iii", "vi"): 0.9,
    },
    "jazz": {
        ("ii", "V"): 1.7,
        ("V", "I"): 1.7,
        ("vi", "ii"): 1.0,
        ("iii", "vi"): 1.0,
        ("V/ii", "ii"): 1.2,
        ("V/V", "V"): 1.2,
    },
    "cinematic": {
        ("i", "bVI"): 1.2,
        ("bVI", "III"): 0.9,
        ("III", "bVII"): 0.9,
        ("bVII", "i"): 1.0,
        ("I", "vi"): 0.7,
        ("vi", "IV"): 0.8,
    },
}


@dataclass(frozen=True)
class KeyContext:
    root: int
    mode: str

    @property
    def name(self) -> str:
        return f"{PITCH_NAMES[self.root]} {self.mode}"


@dataclass(frozen=True)
class HarmonyChord:
    symbol: str
    root: int
    intervals: tuple[int, ...]
    degree: str
    function: str
    color_prior: float

    @property
    def pitch_classes(self) -> frozenset[int]:
        return frozenset((self.root + interval) % 12 for interval in self.intervals)


@dataclass(frozen=True)
class HarmonySlot:
    index: int
    start: float
    length: float
    melody: tuple[Note, ...]
    phrase_end: bool


def plan_piano_harmony(
    notes: list[Note],
    *,
    style: str = "pop",
    complexity: str = "balanced",
    harmonic_rhythm: str = "auto",
    key: str = "auto",
    low_pitch: int = 48,
    high_pitch: int = 76,
    beats_per_bar: float = 4.0,
) -> dict[str, Any]:
    """Plan and voice a deterministic piano accompaniment from a monophonic melody."""
    if len(notes) < 2:
        raise ValueError("melody needs at least two notes")
    if len(notes) > 2048:
        raise ValueError("melody analysis is limited to 2048 notes")
    if style not in SUPPORTED_HARMONY_STYLES:
        raise ValueError(f"style must be one of {', '.join(SUPPORTED_HARMONY_STYLES)}")
    if complexity not in SUPPORTED_COMPLEXITIES:
        raise ValueError(f"complexity must be one of {', '.join(SUPPORTED_COMPLEXITIES)}")
    if harmonic_rhythm not in SUPPORTED_HARMONIC_RHYTHMS:
        raise ValueError(
            f"harmonic_rhythm must be one of {', '.join(SUPPORTED_HARMONIC_RHYTHMS)}"
        )
    if not 24 <= int(low_pitch) <= 84:
        raise ValueError("low_pitch must be between 24 and 84")
    if not 36 <= int(high_pitch) <= 96:
        raise ValueError("high_pitch must be between 36 and 96")
    if int(high_pitch) - int(low_pitch) < 12:
        raise ValueError("piano range must span at least one octave")

    ordered = sorted(notes, key=lambda note: (note.start, note.pitch, note.note_id))
    key_context, key_confidence = _resolve_key(ordered, key, beats_per_bar)
    rhythm_beats = _resolve_harmonic_rhythm(
        ordered, harmonic_rhythm, style, beats_per_bar
    )
    slots = _make_slots(ordered, rhythm_beats, beats_per_bar)
    candidates = _build_candidates(key_context, style, complexity)
    paths = _beam_search(slots, candidates, key_context, style)
    if not paths:
        raise ValueError("could not derive a compatible chord progression")

    evaluated: list[dict[str, Any]] = []
    for path_score, path in paths[:12]:
        voicings = _voice_progression(
            path,
            slots,
            complexity,
            style,
            int(low_pitch),
            int(high_pitch),
        )
        quality = _evaluate_plan(
            path,
            voicings,
            slots,
            key_context,
            style,
            path_score,
        )
        evaluated.append(
            {
                "path": path,
                "path_score": path_score,
                "voicings": voicings,
                "quality": quality,
            }
        )

    evaluated.sort(
        key=lambda item: (
            item["quality"]["overall"],
            item["quality"]["melody_fit"],
            item["path_score"],
        ),
        reverse=True,
    )
    selected = evaluated[0]
    selected_path: tuple[HarmonyChord, ...] = selected["path"]
    selected_voicings: list[list[int]] = selected["voicings"]
    events = _piano_events(
        selected_voicings,
        slots,
        style,
        complexity,
        beats_per_bar,
    )
    if len(events) > 2048:
        raise ValueError("generated piano harmony is limited to 2048 notes")

    progression = []
    for slot, chord, voicing in zip(slots, selected_path, selected_voicings):
        local_scores = sorted(
            (
                _melody_chord_score(slot, option, key_context),
                option.symbol,
            )
            for option in candidates
        )
        best_local = local_scores[-1][0]
        second_local = local_scores[-2][0] if len(local_scores) > 1 else best_local
        confidence = 1.0 / (1.0 + exp(-(best_local - second_local) / 2.5))
        progression.append(
            {
                "slot": slot.index + 1,
                "start_beat": round(slot.start, 4),
                "length_beats": round(slot.length, 4),
                "bar": int(slot.start // beats_per_bar) + 1,
                "beat": round(slot.start % beats_per_bar + 1.0, 4),
                "chord": chord.symbol,
                "degree": chord.degree,
                "function": chord.function,
                "voicing": voicing,
                "confidence": round(max(0.5, min(0.98, confidence)), 3),
                "phrase_end": slot.phrase_end,
            }
        )

    alternatives = []
    seen: set[tuple[str, ...]] = set()
    for item in evaluated[1:]:
        symbols = tuple(chord.symbol for chord in item["path"])
        if symbols in seen or symbols == tuple(chord.symbol for chord in selected_path):
            continue
        seen.add(symbols)
        alternatives.append(
            {
                "chords": list(symbols),
                "score": item["quality"]["overall"],
            }
        )
        if len(alternatives) == 2:
            break

    return {
        "key": key_context.name,
        "key_confidence": round(key_confidence, 3),
        "style": style,
        "complexity": complexity,
        "harmonic_rhythm_beats": rhythm_beats,
        "bar_count": max(
            1,
            ceil(max(note.start + note.length for note in ordered) / beats_per_bar),
        ),
        "progression": progression,
        "timeline_text": timeline_text_from_progression(progression),
        "alternatives": alternatives,
        "quality": {
            **selected["quality"],
            "evaluation_passes": 2,
            "candidate_progressions_compared": len(evaluated),
            "audio_evaluated": False,
        },
        "events": events,
    }


def public_harmony_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key != "events"}


def _resolve_key(
    notes: list[Note], requested: str, beats_per_bar: float
) -> tuple[KeyContext, float]:
    if requested.strip().lower() not in {"", "auto"}:
        return _parse_key(requested), 1.0

    weights = [0.0] * 12
    for note in notes:
        beat = note.start % beats_per_bar
        accent = 1.55 if _near(beat, 0.0) else (1.2 if _near(beat, 2.0) else 1.0)
        duration = max(0.15, min(note.length, beats_per_bar))
        weights[note.pitch % 12] += duration * accent
    end_pitch = notes[-1].pitch % 12

    scored: list[tuple[float, KeyContext]] = []
    profiles = {
        "major": (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88),
        "minor": (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17),
    }
    for root in range(12):
        for mode, profile in profiles.items():
            score = sum(
                weights[pitch] * profile[(pitch - root) % 12] for pitch in range(12)
            )
            scale = frozenset(
                (root + interval) % 12 for interval in _SCALE_INTERVALS[mode]
            )
            scale_weight = sum(weights[pitch] for pitch in scale)
            outside_weight = sum(weights) - scale_weight
            score += scale_weight * 1.5
            score -= outside_weight * 4.0
            if end_pitch == root:
                score += max(weights) * 0.75
            elif mode == "minor" and end_pitch == (root + 3) % 12:
                score += max(weights) * 0.2
            scored.append((score, KeyContext(root, mode)))
    scored.sort(key=lambda item: (item[0], -item[1].root), reverse=True)
    best_score, best = scored[0]
    runner_up = scored[1][0]
    confidence = 0.5 + min(0.48, max(0.0, (best_score - runner_up) / max(1.0, best_score)))
    return best, confidence


def _parse_key(value: str) -> KeyContext:
    compact = value.strip()
    match = re.fullmatch(
        r"([A-Ga-g])([#b]?)(?:(?:\s+)(major|minor|maj|min)|([mM]))?",
        compact,
    )
    if not match:
        raise ValueError("key must be auto or a value such as C major or A minor")
    root_name = (match.group(1).upper() + match.group(2)).upper()
    if root_name not in ROOTS:
        raise ValueError("unsupported key root")
    mode_token = (match.group(3) or "").lower()
    suffix = match.group(4)
    mode = "minor" if mode_token in {"minor", "min"} or suffix == "m" else "major"
    return KeyContext(ROOTS[root_name], mode)


def _resolve_harmonic_rhythm(
    notes: list[Note],
    requested: str,
    style: str,
    beats_per_bar: float,
) -> float:
    fixed = {
        "half_bar": beats_per_bar / 2.0,
        "bar": beats_per_bar,
        "two_bars": beats_per_bar * 2.0,
    }
    if requested in fixed:
        return fixed[requested]

    end = max(note.start + note.length for note in notes)
    density = len(notes) / max(beats_per_bar, end)
    if style in {"jazz", "rnb"} and density >= 1.4:
        return beats_per_bar / 2.0
    if style == "cinematic" and density < 0.65:
        return beats_per_bar * 2.0
    return beats_per_bar


def _make_slots(
    notes: list[Note],
    rhythm_beats: float,
    beats_per_bar: float,
) -> list[HarmonySlot]:
    end = max(note.start + note.length for note in notes)
    count = max(1, ceil(end / rhythm_beats))
    slots = []
    for index in range(count):
        start = index * rhythm_beats
        slot_end = min(end, start + rhythm_beats)
        melody = tuple(
            note
            for note in notes
            if note.start < slot_end and note.start + note.length > start
        )
        next_starts = [note.start for note in notes if note.start >= slot_end]
        gap = min(next_starts) - slot_end if next_starts else beats_per_bar
        phrase_end = (
            index == count - 1
            or gap >= 0.75
            or _near(slot_end % (beats_per_bar * 4.0), 0.0)
        )
        slots.append(
            HarmonySlot(
                index=index,
                start=start,
                length=max(0.25, slot_end - start),
                melody=melody,
                phrase_end=phrase_end,
            )
        )
    return slots


def _build_candidates(
    key: KeyContext,
    style: str,
    complexity: str,
) -> tuple[HarmonyChord, ...]:
    if key.mode == "major":
        degrees = (
            (0, "I", "tonic", "major"),
            (2, "ii", "predominant", "minor"),
            (4, "iii", "tonic", "minor"),
            (5, "IV", "predominant", "major"),
            (7, "V", "dominant", "major"),
            (9, "vi", "tonic", "minor"),
            (11, "vii", "dominant", "dim"),
        )
    else:
        degrees = (
            (0, "i", "tonic", "minor"),
            (2, "ii", "predominant", "dim"),
            (3, "III", "tonic", "major"),
            (5, "iv", "predominant", "minor"),
            (7, "V", "dominant", "major"),
            (8, "bVI", "predominant", "major"),
            (10, "bVII", "dominant", "major"),
        )

    candidates: list[HarmonyChord] = []
    for offset, degree, function, base_quality in degrees:
        root = (key.root + offset) % 12
        for suffix, prior in _quality_variants(
            base_quality, degree, function, style, complexity
        ):
            candidates.append(
                _make_chord(root, suffix, degree, function, prior)
            )

    if key.mode == "major" and style in {"rock", "cinematic"}:
        candidates.extend(
            (
                _make_chord((key.root + 10) % 12, "", "bVII", "dominant", 0.7),
                _make_chord((key.root + 5) % 12, "m", "iv", "predominant", 0.35),
                _make_chord((key.root + 8) % 12, "", "bVI", "predominant", 0.35),
            )
        )
    if complexity == "rich" or style in {"jazz", "rnb"}:
        candidates.extend(
            (
                _make_chord((key.root + 9) % 12, "7", "V/ii", "dominant", 0.2),
                _make_chord((key.root + 2) % 12, "7", "V/V", "dominant", 0.25),
                _make_chord((key.root + 4) % 12, "7", "V/vi", "dominant", 0.2),
            )
        )

    unique: dict[tuple[str, str], HarmonyChord] = {}
    for chord in candidates:
        unique[(chord.symbol, chord.degree)] = chord
    return tuple(unique.values())


def _quality_variants(
    base_quality: str,
    degree: str,
    function: str,
    style: str,
    complexity: str,
) -> tuple[tuple[str, float], ...]:
    if base_quality == "dim":
        if complexity == "simple":
            return (("dim", -0.25),)
        return (("m7b5", 0.0), ("dim", -0.2))

    if base_quality == "major":
        if complexity == "simple":
            return (("7", 0.25), ("", 0.0)) if function == "dominant" else (("", 0.0),)
        if function == "dominant":
            if style == "rock":
                return (("", 0.4), ("7", 0.0))
            variants = [("7", 0.5), ("", 0.0)]
            if complexity == "rich" and style in {"jazz", "rnb"}:
                variants.insert(0, ("9", 0.7))
            return tuple(variants)
        if style == "rock":
            return (("", 0.4), ("sus2", 0.15))
        if style == "pop":
            return (("", 0.3), ("add9", 0.12), ("maj7", -0.1))
        variants = [("", 0.0), ("maj7", 0.25)]
        if style in {"ballad", "rnb", "cinematic"}:
            variants.append(("add9", 0.35))
        if complexity == "rich" and style == "rnb":
            variants.append(("6", 0.2))
        return tuple(variants)

    if complexity == "simple":
        return (("m", 0.0),)
    if style == "rock":
        return (("m", 0.4),)
    if style == "pop":
        return (("m", 0.3), ("m7", -0.05))
    if style == "cinematic":
        return (("m", 0.35), ("m7", 0.05))
    variants = [("m", 0.0), ("m7", 0.25)]
    if style in {"rnb", "jazz"} and complexity == "rich":
        variants.append(("m9", 0.45))
    if style == "ballad":
        variants.append(("m7", 0.35))
    return tuple(variants)


def _make_chord(
    root: int,
    suffix: str,
    degree: str,
    function: str,
    prior: float,
) -> HarmonyChord:
    symbol = f"{PITCH_NAMES[root]}{suffix}"
    parsed_root, intervals = parse_chord(symbol)
    return HarmonyChord(symbol, parsed_root, intervals, degree, function, prior)


def _beam_search(
    slots: list[HarmonySlot],
    candidates: tuple[HarmonyChord, ...],
    key: KeyContext,
    style: str,
) -> list[tuple[float, tuple[HarmonyChord, ...]]]:
    beam: list[tuple[float, tuple[HarmonyChord, ...]]] = [(0.0, ())]
    width = 72
    for slot in slots:
        next_beam: list[tuple[float, tuple[HarmonyChord, ...]]] = []
        for base_score, path in beam:
            for chord in candidates:
                score = base_score + _melody_chord_score(slot, chord, key)
                if path:
                    score += _transition_score(path, chord, style)
                else:
                    if chord.degree in {"I", "i"}:
                        score += 1.5
                    elif chord.function == "tonic":
                        score += 0.25
                    else:
                        score -= 0.25
                if slot.phrase_end and path:
                    score += _cadence_score(path[-1], chord)
                next_beam.append((score, path + (chord,)))
        next_beam.sort(
            key=lambda item: (item[0], tuple(chord.symbol for chord in item[1])),
            reverse=True,
        )
        beam = next_beam[:width]

    finished = [
        (
            score + _terminal_score(path),
            path,
        )
        for score, path in beam
    ]
    finished.sort(
        key=lambda item: (item[0], tuple(chord.symbol for chord in item[1])),
        reverse=True,
    )
    return finished


def _melody_chord_score(
    slot: HarmonySlot,
    chord: HarmonyChord,
    key: KeyContext,
) -> float:
    chord_tones = chord.pitch_classes
    scale = frozenset((key.root + interval) % 12 for interval in _SCALE_INTERVALS[key.mode])
    if not slot.melody:
        return chord.color_prior - 0.15

    total = chord.color_prior
    for note in slot.melody:
        overlap = max(
            0.0,
            min(note.start + note.length, slot.start + slot.length)
            - max(note.start, slot.start),
        )
        relative = max(0.0, note.start - slot.start)
        accent = 1.55 if _near(relative, 0.0) else (1.2 if _near(relative % 2.0, 0.0) else 1.0)
        weight = max(0.15, overlap) * accent
        pitch_class = note.pitch % 12
        if pitch_class in chord_tones:
            total += 3.0 * weight
        elif pitch_class in scale:
            interval = (pitch_class - chord.root) % 12
            tension = 0.55 if interval in {2, 5, 9} else 0.15
            total += tension * weight
        elif note.length <= 0.5 and accent <= 1.0:
            total -= 0.35 * weight
        else:
            total -= 2.4 * weight

    longest = max(slot.melody, key=lambda note: (note.length, -note.start))
    if longest.pitch % 12 in chord_tones:
        total += 1.0
    if chord.root == longest.pitch % 12:
        total += 0.15
    return total


def _transition_score(
    path: tuple[HarmonyChord, ...],
    current: HarmonyChord,
    style: str,
) -> float:
    previous = path[-1]
    score = _FUNCTION_TRANSITIONS.get((previous.function, current.function), 0.0)
    score += _STYLE_TRANSITIONS.get(style, {}).get((previous.degree, current.degree), 0.0)
    root_motion = (current.root - previous.root) % 12
    if root_motion in {5, 7}:
        score += 0.45
    elif root_motion in {1, 11}:
        score -= 0.15
    if previous.symbol == current.symbol:
        score += 0.15 if len(path) == 1 or path[-2].symbol != current.symbol else -1.4
    if current.degree.startswith("V/"):
        score -= 0.1
    if previous.degree.startswith("V/"):
        target = previous.degree.removeprefix("V/")
        score += 1.25 if current.degree == target else -0.8
    return score


def _cadence_score(previous: HarmonyChord, current: HarmonyChord) -> float:
    if previous.function == "dominant" and current.degree in {"I", "i"}:
        return 2.5
    if previous.function == "dominant" and current.degree == "vi":
        return 1.0
    if previous.degree in {"IV", "iv"} and current.degree in {"I", "i"}:
        return 1.4
    if current.degree in {"I", "i"}:
        return 0.8
    if current.function == "tonic":
        return 0.2
    return -0.35


def _terminal_score(path: tuple[HarmonyChord, ...]) -> float:
    if not path:
        return -100.0
    if path[-1].degree in {"I", "i"}:
        score = 2.2
    elif path[-1].function == "tonic":
        score = -0.1
    else:
        score = -0.7
    if len(path) >= 2:
        score += _cadence_score(path[-2], path[-1])
    return score


def _voice_progression(
    path: tuple[HarmonyChord, ...],
    slots: list[HarmonySlot],
    complexity: str,
    style: str,
    low_pitch: int,
    high_pitch: int,
) -> list[list[int]]:
    voicings: list[list[int]] = []
    previous: list[int] | None = None
    for chord, slot in zip(path, slots):
        options = _voicing_options(chord, complexity, low_pitch, high_pitch)
        melody_center = (
            median(note.pitch for note in slot.melody) if slot.melody else high_pitch + 5
        )
        target_top = min(high_pitch, int(melody_center) - 2)
        scored = []
        for option in options:
            register_penalty = abs(median(option) - (low_pitch + high_pitch) / 2.0) * 0.25
            melody_penalty = max(0, option[-1] - target_top) * 0.8
            movement = _voicing_movement(previous, option) if previous else 0.0
            bass_penalty = (
                max(0, abs(option[0] - previous[0]) - 7) * 0.7 if previous else 0.0
            )
            common_bonus = (
                len(set(previous or ()) & set(option)) * (1.0 if style != "rock" else 0.5)
            )
            scored.append(
                (
                    movement + register_penalty + melody_penalty + bass_penalty - common_bonus,
                    option,
                )
            )
        scored.sort(key=lambda item: (item[0], item[1]))
        selected = list(scored[0][1])
        voicings.append(selected)
        previous = selected
    return voicings


def _voicing_options(
    chord: HarmonyChord,
    complexity: str,
    low_pitch: int,
    high_pitch: int,
) -> list[tuple[int, ...]]:
    max_voices = {"simple": 3, "balanced": 4, "rich": 5}[complexity]
    intervals = list(chord.intervals[:max_voices])
    if len(intervals) < 3:
        intervals = list(chord.intervals)
    options: set[tuple[int, ...]] = set()
    for inversion in range(len(intervals)):
        rotated = intervals[inversion:] + [value + 12 for value in intervals[:inversion]]
        for octave in range(2, 7):
            root_pitch = 12 * (octave + 1) + chord.root
            voiced = tuple(root_pitch + value for value in rotated)
            while voiced and voiced[0] < low_pitch:
                voiced = tuple(value + 12 for value in voiced)
            while voiced and voiced[-1] > high_pitch:
                voiced = tuple(value - 12 for value in voiced)
            if (
                voiced
                and voiced[0] >= low_pitch
                and voiced[-1] <= high_pitch
                and voiced[-1] - voiced[0] <= 24
            ):
                options.add(voiced)
    if not options:
        base = 12 * 5 + chord.root
        voiced = tuple(base + value for value in intervals)
        shift = 0
        while min(voiced) + shift < low_pitch:
            shift += 12
        while max(voiced) + shift > high_pitch:
            shift -= 12
        options.add(tuple(max(0, min(127, value + shift)) for value in voiced))
    return sorted(options)


def _voicing_movement(previous: list[int] | None, current: tuple[int, ...]) -> float:
    if not previous:
        return 0.0
    left = list(previous)
    right = list(current)
    count = min(len(left), len(right))
    movement = sum(abs(left[index] - right[index]) for index in range(count))
    movement += 4 * abs(len(left) - len(right))
    return movement / max(1, count)


def _evaluate_plan(
    path: tuple[HarmonyChord, ...],
    voicings: list[list[int]],
    slots: list[HarmonySlot],
    key: KeyContext,
    style: str,
    path_score: float,
) -> dict[str, Any]:
    fit_points = 0.0
    fit_total = 0.0
    scale = frozenset((key.root + interval) % 12 for interval in _SCALE_INTERVALS[key.mode])
    for slot, chord in zip(slots, path):
        for note in slot.melody:
            overlap = max(
                0.0,
                min(note.start + note.length, slot.start + slot.length)
                - max(note.start, slot.start),
            )
            accent = 1.5 if _near((note.start - slot.start) % 4.0, 0.0) else 1.0
            weight = max(0.15, overlap) * accent
            fit_total += weight
            if note.pitch % 12 in chord.pitch_classes:
                fit_points += weight
            elif note.pitch % 12 in scale:
                fit_points += weight * 0.62
            elif note.length <= 0.5:
                fit_points += weight * 0.25
    melody_fit = 100.0 * fit_points / max(0.001, fit_total)

    movements = [
        _voicing_movement(list(previous), tuple(current))
        for previous, current in pairwise(voicings)
    ]
    average_movement = sum(movements) / max(1, len(movements))
    voice_leading = max(0.0, min(100.0, 100.0 - average_movement * 8.0))

    boundaries = [
        index for index, slot in enumerate(slots) if slot.phrase_end and index > 0
    ]
    cadence_values = [
        max(0.0, min(100.0, 45.0 + 25.0 * _cadence_score(path[index - 1], path[index])))
        for index in boundaries
    ]
    cadence = sum(cadence_values) / max(1, len(cadence_values))
    if not cadence_values:
        cadence = 70.0 if path[-1].function == "tonic" else 45.0

    style_pairs = _STYLE_TRANSITIONS.get(style, {})
    pair_scores = [
        style_pairs.get((previous.degree, current.degree), 0.0)
        for previous, current in pairwise(path)
    ]
    style_fit = max(
        45.0,
        min(100.0, 65.0 + 18.0 * (sum(pair_scores) / max(1, len(pair_scores)))),
    )
    longest_repeat = 1
    repeat = 1
    for previous, current in pairwise(path):
        repeat = repeat + 1 if previous.symbol == current.symbol else 1
        longest_repeat = max(longest_repeat, repeat)
    variety = max(
        35.0,
        min(
            100.0,
            70.0
            + 30.0 * len({chord.symbol for chord in path}) / max(1, len(path))
            - max(0, longest_repeat - 2) * 20.0,
        ),
    )
    overall = (
        melody_fit * 0.42
        + voice_leading * 0.22
        + cadence * 0.15
        + style_fit * 0.13
        + variety * 0.08
    )
    return {
        "overall": round(max(0.0, min(100.0, overall)), 1),
        "melody_fit": round(melody_fit, 1),
        "voice_leading": round(voice_leading, 1),
        "cadence": round(cadence, 1),
        "style_fit": round(style_fit, 1),
        "variety": round(variety, 1),
        "average_voice_motion_semitones": round(average_movement, 2),
        "structural_path_score": round(path_score, 2),
    }


def _piano_events(
    voicings: list[list[int]],
    slots: list[HarmonySlot],
    style: str,
    complexity: str,
    beats_per_bar: float,
) -> list[dict[str, Any]]:
    patterns = {
        "pop": ((0.0, 0.46, 84), (0.5, 0.44, 78)),
        "ballad": ((0.0, 0.94, 74),),
        "rock": (
            (0.0, 0.22, 92),
            (0.25, 0.20, 82),
            (0.5, 0.22, 88),
            (0.75, 0.20, 82),
        ),
        "rnb": ((0.0, 0.28, 77), (0.375, 0.18, 70), (0.75, 0.20, 80)),
        "jazz": ((0.0, 0.24, 76), (0.375, 0.16, 68), (0.75, 0.18, 74)),
        "cinematic": ((0.0, 0.96, 70),),
    }
    pattern = patterns[style]
    if complexity == "simple":
        pattern = pattern[:1] if style not in {"rock"} else pattern[::2]
    roll = 0.025 if style in {"ballad", "cinematic"} and complexity != "simple" else 0.0

    events: list[dict[str, Any]] = []
    for slot, voicing in zip(slots, voicings):
        for fraction, duration_fraction, velocity in pattern:
            attack = slot.start + fraction * slot.length
            duration = min(
                slot.length * duration_fraction,
                slot.start + slot.length - attack,
            )
            if duration <= 0.05:
                continue
            for voice_index, pitch in enumerate(voicing):
                offset = roll * voice_index
                start = attack + offset
                length = max(0.08, duration - offset)
                events.append(
                    {
                        "bar": int(start // beats_per_bar) + 1,
                        "b": round(start % beats_per_bar + 1.0, 5),
                        "t": 0,
                        "n": pitch,
                        "v": max(1, min(127, velocity - voice_index * 2)),
                        "l": round(length, 5),
                        "channel": 1,
                    }
                )
    return events


def _near(value: float, target: float, tolerance: float = 0.06) -> bool:
    return abs(value - target) <= tolerance
