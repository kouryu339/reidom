# FL Studio adapter

Target: MIDI script or export/import bridge.

FL Studio has a huge user base, but Reidom should be conservative here: focus on
piano-roll MIDI assistance first.

## Phase 1

- Verify the supported scripting surface for active piano-roll notes.
- If direct selection read is limited, provide a manual export/import bridge.
- Publish to `reidom-midi-selection/v1` with `capabilities.read_midi_selection`
  marked as `limited`.

## Phase 2

- Preview as a generated pattern or imported MIDI clip.
- Apply only through a visible user action inside FL Studio.

## Product rule

Do not market FL support as deep project editing until we have a tested script or
plugin path.
