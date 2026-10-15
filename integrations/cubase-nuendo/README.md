# Cubase / Nuendo adapter

Target: MIDI Remote or VST3 companion plugin.

Cubase/Nuendo support is valuable for professional composers, but the first safe
path may be a plugin bridge rather than deep project scripting.

## Phase 1

- Verify whether MIDI Remote can expose enough note/selection context.
- If not, use a VST3 companion plugin as the bridge surface.
- Keep the frontend capability as `plugin_fallback` until proven.

## Product rule

Cubase/Nuendo should be shown in Reidom Studio as a planned professional target,
not as ready deep editing support.
