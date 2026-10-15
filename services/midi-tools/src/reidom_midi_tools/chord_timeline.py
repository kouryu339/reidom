from __future__ import annotations

import random
import re
from dataclasses import dataclass
from math import ceil
from statistics import median
from typing import Any

from .music_copilot import ROOTS, parse_chord

SUPPORTED_ARP_DIRECTIONS = ("up", "down", "updown", "alberti", "random")
_ENTRY_PATTERN = re.compile(
    r"(?P<symbol>[A-Ga-g](?:#|b)?[A-Za-z0-9#b]*(?:/[A-Ga-g](?:#|b)?)?)"
    r"\s*\((?P<duration>\d+(?:\.\d+)?)\)"
    r"(?:\s*\{(?P<performance>[^{}]+)\})?"
)
_HEADER_PATTERN = re.compile(
    r"^\s*(?P<numerator>\d+)/(?P<denominator>\d+)"
    r"\s+@(?P<start_bar>\d+):(?P<start_beat>\d+(?:\.\d+)?)"
    r"-(?P<end_bar>\d+):(?P<end_beat>\d+(?:\.\d+)?)"
    r"\s*\|\s*(?P<body>.+?)\s*$"
)


@dataclass(frozen=True)
class Performance:
    mode: str
    direction: str | None = None
    rate_beats: float | None = None
    rate_text: str | None = None
    octaves: int = 1
    gate: float = 0.9
    seed: int = 0


@dataclass(frozen=True)
class TimelineChord:
    symbol: str
    root: int
    intervals: tuple[int, ...]
    bass: int | None
    start: float
    duration: float
    performance: Performance


@dataclass(frozen=True)
class ChordTimeline:
    meter: str
    start: float
    end: float
    start_bar: int
    start_beat: float
    end_bar: int
    end_beat: float
    performance: Performance
    chords: tuple[TimelineChord, ...]


def build_chord_timeline(
    text: str,
    *,
    low_pitch: int = 48,
    high_pitch: int = 76,
    velocity: int = 80,
) -> dict[str, Any]:
    timeline = parse_chord_timeline(text)
    _validate_render_range(low_pitch, high_pitch, velocity)
    voicings = _voice_timeline(timeline, int(low_pitch), int(high_pitch))
    events: list[dict[str, Any]] = []
    rendered_chords: list[dict[str, Any]] = []

    for index, (chord, voicing) in enumerate(zip(timeline.chords, voicings)):
        events.extend(
            _performance_events(
                chord,
                list(voicing),
                index,
                int(low_pitch),
                int(high_pitch),
                int(velocity),
            )
        )
        start_bar, start_beat = _offset_to_bbt(chord.start)
        end_bar, end_beat = _offset_to_bbt(chord.start + chord.duration)
        rendered_chords.append(
            {
                "index": index + 1,
                "symbol": chord.symbol,
                "start": _format_bbt(start_bar, start_beat),
                "end": _format_bbt(end_bar, end_beat),
                "duration_beats": chord.duration,
                "voicing": list(voicing),
                "performance": _performance_dict(chord.performance),
                "role": "short_harmony" if chord.duration <= 1.0 else "harmony",
            }
        )

    if len(events) > 2048:
        raise ValueError("chord timeline is limited to 2048 generated notes")

    return {
        "meter": timeline.meter,
        "range": {
            "start": _format_bbt(timeline.start_bar, timeline.start_beat),
            "end": _format_bbt(timeline.end_bar, timeline.end_beat),
            "length_beats": timeline.end - timeline.start,
        },
        "timeline_text": format_chord_timeline(timeline),
        "performance": _performance_dict(timeline.performance),
        "chords": rendered_chords,
        "short_chord_count": sum(
            1 for chord in timeline.chords if chord.duration <= 1.0
        ),
        "events": events,
    }


def parse_chord_timeline(text: str) -> ChordTimeline:
    compact = _normalize_text(text)
    if not compact:
        raise ValueError("timeline is required")

    harmonic_text, separator, performance_text = compact.partition("||")
    if separator and "||" in performance_text:
        raise ValueError("timeline may contain only one global performance clause")
    performance = _parse_performance(performance_text.strip() or "block")

    match = _HEADER_PATTERN.fullmatch(harmonic_text.strip())
    if not match:
        raise ValueError(
            "timeline must look like 4/4 @1:1-5:1 | Am7(4) Fmaj7(4)"
        )
    numerator = int(match.group("numerator"))
    denominator = int(match.group("denominator"))
    if (numerator, denominator) != (4, 4):
        raise ValueError("chord timeline currently supports 4/4 only")

    start_bar = int(match.group("start_bar"))
    start_beat = float(match.group("start_beat"))
    end_bar = int(match.group("end_bar"))
    end_beat = float(match.group("end_beat"))
    _validate_bbt(start_bar, start_beat, "start")
    _validate_bbt(end_bar, end_beat, "end")
    start = _bbt_to_offset(start_bar, start_beat)
    end = _bbt_to_offset(end_bar, end_beat)
    if end <= start:
        raise ValueError("timeline end must be after its start")
    if end - start > 512:
        raise ValueError("timeline range is limited to 512 beats")

    body = match.group("body")
    parsed: list[tuple[str, float, Performance]] = []
    cursor = 0
    for item in _ENTRY_PATTERN.finditer(body):
        _validate_entry_gap(body[cursor : item.start()])
        symbol = item.group("symbol")
        duration = float(item.group("duration"))
        if not 0.25 <= duration <= 64.0:
            raise ValueError("each chord duration must be between 0.25 and 64 beats")
        local_text = (item.group("performance") or "").strip()
        local_performance = (
            _parse_performance(local_text, inherit=performance)
            if local_text
            else performance
        )
        _parse_chord_symbol(symbol)
        parsed.append((symbol, duration, local_performance))
        cursor = item.end()
    _validate_entry_gap(body[cursor:])

    if not parsed:
        raise ValueError("timeline must contain at least one Chord(beats) item")
    if len(parsed) > 128:
        raise ValueError("timeline is limited to 128 chord changes")

    total_duration = sum(duration for _, duration, _ in parsed)
    range_duration = end - start
    if abs(total_duration - range_duration) > 0.001:
        raise ValueError(
            f"chord durations total {_format_number(total_duration)} beats, "
            f"but the range spans {_format_number(range_duration)} beats"
        )

    chords: list[TimelineChord] = []
    chord_start = start
    for symbol, duration, local_performance in parsed:
        root, intervals, bass = _parse_chord_symbol(symbol)
        chords.append(
            TimelineChord(
                symbol=symbol,
                root=root,
                intervals=intervals,
                bass=bass,
                start=chord_start,
                duration=duration,
                performance=local_performance,
            )
        )
        chord_start += duration

    return ChordTimeline(
        meter="4/4",
        start=start,
        end=end,
        start_bar=start_bar,
        start_beat=start_beat,
        end_bar=end_bar,
        end_beat=end_beat,
        performance=performance,
        chords=tuple(chords),
    )


def format_chord_timeline(timeline: ChordTimeline) -> str:
    chord_text = " ".join(
        f"{chord.symbol}({_format_number(chord.duration)})"
        + (
            f"{{{_format_performance(chord.performance)}}}"
            if chord.performance != timeline.performance
            else ""
        )
        for chord in timeline.chords
    )
    return (
        f"{timeline.meter} "
        f"@{_format_bbt(timeline.start_bar, timeline.start_beat)}"
        f"-{_format_bbt(timeline.end_bar, timeline.end_beat)}"
        f" | {chord_text} || {_format_performance(timeline.performance)}"
    )


def timeline_text_from_progression(
    progression: list[dict[str, Any]],
    *,
    performance: str = "block",
) -> str:
    if not progression:
        raise ValueError("progression is required")
    chords = []
    end = 0.0
    for item in progression:
        symbol = str(item.get("chord") or "").strip()
        duration = float(item.get("length_beats") or 0.0)
        if not symbol or duration <= 0:
            raise ValueError("progression needs chord and length_beats for every item")
        chords.append(f"{symbol}({_format_number(duration)})")
        end = max(end, float(item.get("start_beat") or 0.0) + duration)
    end_bar, end_beat = _offset_to_bbt(end)
    text = (
        f"4/4 @1:1-{_format_bbt(end_bar, end_beat)} | "
        f"{' '.join(chords)} || {performance}"
    )
    return format_chord_timeline(parse_chord_timeline(text))


def public_chord_timeline(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key != "events"}


def _normalize_text(text: str) -> str:
    return (
        str(text or "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("：", ":")
        .replace("｜", "|")
        .replace("－", "-")
        .strip()
    )


def _validate_entry_gap(gap: str) -> None:
    cleaned = re.sub(r"[\s,，>→\-–—]+", "", gap)
    if cleaned:
        raise ValueError(f"unsupported timeline text near: {gap.strip()}")


def _validate_bbt(bar: int, beat: float, label: str) -> None:
    if bar < 1:
        raise ValueError(f"{label} bar must be at least 1")
    if not 1.0 <= beat < 5.0:
        raise ValueError(f"{label} beat must be at least 1 and below 5 in 4/4")


def _bbt_to_offset(bar: int, beat: float) -> float:
    return (bar - 1) * 4.0 + (beat - 1.0)


def _offset_to_bbt(offset: float) -> tuple[int, float]:
    bar = int(offset // 4.0) + 1
    beat = offset % 4.0 + 1.0
    return bar, round(beat, 5)


def _format_bbt(bar: int, beat: float) -> str:
    return f"{bar}:{_format_number(beat)}"


def _format_number(value: float) -> str:
    if abs(value - round(value)) <= 0.00001:
        return str(round(value))
    return f"{value:.5f}".rstrip("0").rstrip(".")


def _parse_chord_symbol(symbol: str) -> tuple[int, tuple[int, ...], int | None]:
    parts = symbol.split("/")
    if len(parts) > 2:
        raise ValueError(f"unsupported slash chord: {symbol}")
    root, intervals = parse_chord(parts[0])
    if len(parts) == 1:
        return root, intervals, None
    bass_name = parts[1].upper()
    if bass_name not in ROOTS:
        raise ValueError(f"unsupported slash bass: {symbol}")
    return root, intervals, ROOTS[bass_name]


def _parse_performance(
    text: str,
    *,
    inherit: Performance | None = None,
) -> Performance:
    compact = text.strip().lower()
    if compact == "block":
        return Performance(mode="block", gate=0.92)
    match = re.fullmatch(r"arp\s*\((.*)\)", compact)
    if not match:
        raise ValueError(
            "performance must be block or arp(up, rate=1/8, oct=2, gate=0.85)"
        )

    base = (
        inherit
        if inherit is not None and inherit.mode == "arp"
        else Performance(
            mode="arp",
            direction="up",
            rate_beats=0.5,
            rate_text="1/8",
            octaves=1,
            gate=0.85,
            seed=0,
        )
    )
    direction = base.direction or "up"
    rate_beats = base.rate_beats or 0.5
    rate_text = base.rate_text or "1/8"
    octaves = base.octaves
    gate = base.gate
    seed = base.seed

    tokens = [token.strip() for token in match.group(1).split(",") if token.strip()]
    for index, token in enumerate(tokens):
        if "=" not in token:
            if index != 0 or token not in SUPPORTED_ARP_DIRECTIONS:
                raise ValueError(
                    f"arp direction must be one of {', '.join(SUPPORTED_ARP_DIRECTIONS)}"
                )
            direction = token
            continue
        key, value = (part.strip() for part in token.split("=", 1))
        if key == "rate":
            rate_beats, rate_text = _parse_rate(value)
        elif key in {"oct", "octaves"}:
            octaves = int(value)
            if not 1 <= octaves <= 3:
                raise ValueError("arp oct must be between 1 and 3")
        elif key == "gate":
            gate = float(value)
            if not 0.1 <= gate <= 1.25:
                raise ValueError("arp gate must be between 0.1 and 1.25")
        elif key == "seed":
            seed = int(value)
            if not 0 <= seed <= 2_147_483_647:
                raise ValueError("arp seed must be between 0 and 2147483647")
        else:
            raise ValueError(f"unsupported arp option: {key}")

    return Performance(
        mode="arp",
        direction=direction,
        rate_beats=rate_beats,
        rate_text=rate_text,
        octaves=octaves,
        gate=gate,
        seed=seed,
    )


def _parse_rate(value: str) -> tuple[float, str]:
    if "/" in value:
        parts = value.split("/")
        if len(parts) != 2:
            raise ValueError("arp rate must be a note value such as 1/8")
        numerator, denominator = (int(part) for part in parts)
        if numerator <= 0 or denominator <= 0:
            raise ValueError("arp rate must be positive")
        beats = 4.0 * numerator / denominator
        text = f"{numerator}/{denominator}"
    else:
        beats = float(value)
        text = _format_number(beats)
    if not 0.125 <= beats <= 4.0:
        raise ValueError("arp rate must be between 1/32 and one whole note")
    return beats, text


def _format_performance(performance: Performance) -> str:
    if performance.mode == "block":
        return "block"
    parts = [
        performance.direction or "up",
        f"rate={performance.rate_text or _format_number(performance.rate_beats or 0.5)}",
        f"oct={performance.octaves}",
        f"gate={_format_number(performance.gate)}",
    ]
    if performance.direction == "random" or performance.seed:
        parts.append(f"seed={performance.seed}")
    return f"arp({', '.join(parts)})"


def _performance_dict(performance: Performance) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": performance.mode,
        "gate": performance.gate,
    }
    if performance.mode == "arp":
        result.update(
            {
                "direction": performance.direction,
                "rate": performance.rate_text,
                "rate_beats": performance.rate_beats,
                "octaves": performance.octaves,
                "seed": performance.seed,
            }
        )
    return result


def _validate_render_range(low_pitch: int, high_pitch: int, velocity: int) -> None:
    if not 24 <= int(low_pitch) <= 84:
        raise ValueError("low_pitch must be between 24 and 84")
    if not 36 <= int(high_pitch) <= 96:
        raise ValueError("high_pitch must be between 36 and 96")
    if int(high_pitch) - int(low_pitch) < 12:
        raise ValueError("chord range must span at least one octave")
    if not 1 <= int(velocity) <= 127:
        raise ValueError("velocity must be between 1 and 127")


def _voice_timeline(
    timeline: ChordTimeline,
    low_pitch: int,
    high_pitch: int,
) -> list[tuple[int, ...]]:
    voicings: list[tuple[int, ...]] = []
    previous: tuple[int, ...] | None = None
    for chord in timeline.chords:
        reserve = (
            12 * (chord.performance.octaves - 1)
            if chord.performance.mode == "arp"
            else 0
        )
        options = _voicing_options(chord, low_pitch, high_pitch)
        scored = []
        for option in options:
            movement = _voice_movement(previous, option)
            center_penalty = abs(median(option) - (low_pitch + high_pitch) / 2.0) * 0.2
            reserve_penalty = max(0, option[-1] + reserve - high_pitch) * 1.2
            bass_leap = (
                max(0, abs(option[0] - previous[0]) - 7) * 0.65
                if previous
                else 0.0
            )
            common_bonus = len(set(previous or ()) & set(option)) * 0.8
            scored.append(
                (
                    movement
                    + center_penalty
                    + reserve_penalty
                    + bass_leap
                    - common_bonus,
                    option,
                )
            )
        scored.sort(key=lambda item: (item[0], item[1]))
        selected = scored[0][1]
        voicings.append(selected)
        previous = selected
    return voicings


def _voicing_options(
    chord: TimelineChord,
    low_pitch: int,
    high_pitch: int,
) -> list[tuple[int, ...]]:
    intervals = list(chord.intervals[:5])
    options: set[tuple[int, ...]] = set()
    for inversion in range(len(intervals)):
        rotated = sorted(
            intervals[inversion:] + [value + 12 for value in intervals[:inversion]]
        )
        for octave in range(2, 7):
            root_pitch = 12 * (octave + 1) + chord.root
            voiced = tuple(root_pitch + value for value in rotated)
            if voiced[0] < low_pitch or voiced[-1] > high_pitch:
                continue
            voiced = _apply_slash_bass(voiced, chord.bass, low_pitch)
            if not voiced or voiced[0] < low_pitch or voiced[-1] > high_pitch:
                continue
            if voiced[-1] - voiced[0] <= 28:
                options.add(voiced)
    if not options:
        raise ValueError(
            f"could not voice {chord.symbol} inside MIDI range {low_pitch}-{high_pitch}"
        )
    return sorted(options)


def _apply_slash_bass(
    voicing: tuple[int, ...],
    bass: int | None,
    low_pitch: int,
) -> tuple[int, ...] | None:
    if bass is None:
        return voicing
    if voicing[0] % 12 == bass:
        return voicing
    candidates = [
        pitch for pitch in range(low_pitch, voicing[0]) if pitch % 12 == bass
    ]
    if not candidates:
        return None
    bass_pitch = candidates[-1]
    return tuple(sorted({bass_pitch, *voicing}))


def _voice_movement(
    previous: tuple[int, ...] | None,
    current: tuple[int, ...],
) -> float:
    if not previous:
        return 0.0
    count = min(len(previous), len(current))
    movement = sum(
        abs(previous[index] - current[index]) for index in range(count)
    )
    movement += 4 * abs(len(previous) - len(current))
    return movement / max(1, count)


def _performance_events(
    chord: TimelineChord,
    voicing: list[int],
    chord_index: int,
    low_pitch: int,
    high_pitch: int,
    velocity: int,
) -> list[dict[str, Any]]:
    performance = chord.performance
    if performance.mode == "block":
        length = max(0.08, chord.duration * performance.gate)
        return [
            _event_at_offset(chord.start, pitch, velocity - index * 2, length)
            for index, pitch in enumerate(voicing)
        ]

    rate = performance.rate_beats or 0.5
    pool = _arpeggio_pool(
        voicing,
        performance.octaves,
        low_pitch,
        high_pitch,
    )
    sequence = _arpeggio_sequence(
        pool,
        performance.direction or "up",
        chord_index,
        performance.seed,
    )
    step_count = max(1, ceil(chord.duration / rate))
    events = []
    for step in range(step_count):
        start = chord.start + step * rate
        remaining = chord.start + chord.duration - start
        if remaining <= 0.00001:
            break
        pitch = sequence[step % len(sequence)]
        accent = 5 if abs(start % 4.0) <= 0.00001 else (2 if step % 2 == 0 else 0)
        length = max(0.05, min(rate * performance.gate, remaining))
        events.append(
            _event_at_offset(
                start,
                pitch,
                max(1, min(127, velocity + accent)),
                length,
            )
        )
    return events


def _arpeggio_pool(
    voicing: list[int],
    octaves: int,
    low_pitch: int,
    high_pitch: int,
) -> list[int]:
    pitches = {
        pitch + 12 * octave
        for octave in range(octaves)
        for pitch in voicing
        if low_pitch <= pitch + 12 * octave <= high_pitch
    }
    return sorted(pitches) or sorted(voicing)


def _arpeggio_sequence(
    pitches: list[int],
    direction: str,
    chord_index: int,
    seed: int,
) -> list[int]:
    if direction == "up":
        return pitches
    if direction == "down":
        return list(reversed(pitches))
    if direction == "updown":
        return pitches + list(reversed(pitches[1:-1] or pitches))
    if direction == "alberti":
        if len(pitches) < 3:
            return pitches
        return [pitches[0], pitches[-1], pitches[1], pitches[-1]]
    rng = random.Random(f"{seed}:{chord_index}:{','.join(map(str, pitches))}")
    shuffled = list(pitches)
    rng.shuffle(shuffled)
    return shuffled


def _event_at_offset(
    offset: float,
    pitch: int,
    velocity: int,
    length: float,
) -> dict[str, Any]:
    bar, beat = _offset_to_bbt(offset)
    return {
        "bar": bar,
        "b": beat,
        "t": 0,
        "n": pitch,
        "v": velocity,
        "l": round(length, 5),
        "channel": 1,
    }
