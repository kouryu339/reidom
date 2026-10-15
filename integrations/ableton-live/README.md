# Ableton Live adapter

Target: Max for Live device first; Remote Script later if needed.

Ableton is clip/session-oriented, so the first bridge should work at active MIDI
clip level instead of pretending to edit the entire Live Set.

## Phase 1

- Detect the selected or appointed MIDI clip.
- Export visible notes and clip timing into `reidom-midi-selection/v1`.
- Include clip identity and Live Set revision hints in `source`.

## Phase 2

- Preview by writing into a duplicate clip or separate preview track.
- Apply only after user confirmation in Reidom Studio.

## Product rule

Ableton support should be advertised as "clip-level arrangement assistance" until
project-wide editing is proven.
