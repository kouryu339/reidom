# Studio One adapter

Target: extension or plugin bridge.

Studio One is important commercially, but Reidom should first verify whether its
extension surface can safely expose MIDI selection state.

## Phase 1

- Verify extension API access to MIDI notes and selections.
- If limited, fall back to plugin/export workflow.
- Keep capabilities conservative in `integrations/adapters.json`.

## Product rule

Prefer honest partial support over a broad claim that breaks trust with working
producers.
