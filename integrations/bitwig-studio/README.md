# Bitwig Studio adapter

Target: Java controller extension.

Bitwig is a strong second-wave adapter because its controller-extension model is
cross-platform and friendly to external control surfaces.

## Phase 1

- Mirror selected clip notes into `reidom-midi-selection/v1`.
- Publish transport, tempo, and clip launcher context when available.
- Keep the extension non-destructive.

## Phase 2

- Preview into a duplicate clip or preview lane.
- Apply accepted edit plans through host-managed undo.

## Product rule

Treat Bitwig as clip-level first. Do not promise arbitrary arranger timeline
editing until the extension proves the exact safe surface.
