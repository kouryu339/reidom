from __future__ import annotations

from dataclasses import dataclass

GENERAL_MIDI_SYNTH_PLUGIN_ID = "lv2:http://gareus.org/oss/lv2/gmsynth"


@dataclass(frozen=True)
class InstrumentPreset:
    key: str
    label: str
    aliases: tuple[str, ...]
    program: int
    channel: int = 0
    bank: int = 0
    patch_name: str = ""
    plugin_id: str = GENERAL_MIDI_SYNTH_PLUGIN_ID


INSTRUMENT_PRESETS: tuple[InstrumentPreset, ...] = (
    InstrumentPreset(
        key="piano",
        label="piano",
        aliases=("piano", "grand piano", "acoustic piano", "钢琴", "原声钢琴"),
        program=0,
        patch_name="Acoustic Grand Piano",
    ),
    InstrumentPreset(
        key="electric_piano",
        label="electric piano",
        aliases=("electric piano", "e-piano", "rhodes", "wurlitzer", "电钢", "电钢琴"),
        program=4,
        patch_name="Electric Piano 1",
    ),
    InstrumentPreset(
        key="electric_guitar",
        label="electric guitar",
        aliases=("electric guitar", "电吉他"),
        program=27,
        patch_name="Clean Electric Guitar",
    ),
    InstrumentPreset(
        key="acoustic_guitar",
        label="acoustic guitar",
        aliases=("acoustic guitar", "steel guitar", "木吉他", "原声吉他"),
        program=25,
        patch_name="Steel String Guitar",
    ),
    InstrumentPreset(
        key="electric_bass",
        label="electric bass",
        aliases=("electric bass", "bass", "电贝斯", "贝斯"),
        program=33,
        patch_name="Fingered Electric Bass",
    ),
    InstrumentPreset(
        key="drums",
        label="drums",
        aliases=("drums", "drum kit", "鼓", "架子鼓"),
        program=0,
        channel=9,
        patch_name="Standard Drum Kit",
    ),
    InstrumentPreset(
        key="strings",
        label="strings",
        aliases=("strings", "string ensemble", "弦乐", "弦乐组"),
        program=48,
        patch_name="String Ensemble 1",
    ),
    InstrumentPreset(
        key="organ",
        label="organ",
        aliases=("organ", "hammond", "风琴", "管风琴"),
        program=16,
        patch_name="Drawbar Organ",
    ),
    InstrumentPreset(
        key="synth",
        label="synth",
        aliases=("synth", "synthesizer", "合成器"),
        program=80,
        patch_name="Square Lead",
    ),
)


def supported_preset_keys() -> tuple[str, ...]:
    return tuple(preset.key for preset in INSTRUMENT_PRESETS)


def resolve_instrument_preset(value: str) -> InstrumentPreset | None:
    normalized = _normalize(value)
    for preset in INSTRUMENT_PRESETS:
        if normalized == _normalize(preset.key):
            return preset
        if any(normalized == _normalize(alias) for alias in preset.aliases):
            return preset
    return None


def find_required_plugin(plugins: list[dict[str, object]]) -> dict[str, object] | None:
    expected = _normalize(GENERAL_MIDI_SYNTH_PLUGIN_ID)
    for plugin in plugins:
        if plugin.get("isInstrument") is not True:
            continue
        plugin_id = _normalize(str(plugin.get("pluginId") or ""))
        unique_id = _normalize(str(plugin.get("uniqueId") or ""))
        if plugin_id == expected or unique_id == _normalize(
            "http://gareus.org/oss/lv2/gmsynth"
        ):
            return plugin
    return None


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())
