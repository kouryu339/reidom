# REAPER adapter

Target: ReaScript file bridge.

REAPER is the fastest non-GPL adapter to prototype because users can install a
Lua ReaScript without rebuilding the DAW.

## Phase 1

- Read selected MIDI item or active MIDI editor take.
- Export notes into `reidom-midi-selection/v1`.
- Write to `data/bridge/adapters/reaper/current-selection.json`.
- Keep all writes one-way and non-destructive.

## Phase 2

- Poll `data/bridge/adapters/reaper/commands`.
- Render preview edits in a temporary item or muted duplicate.
- Apply accepted edits inside a REAPER undo block.

## Product rule

If the adapter cannot prove a selected item/take identity, it must refuse to
apply edits and ask the frontend to refresh the selection.
