# Product requirements

## Product statement

Reidom is a focused MIDI arranging application with an embedded Copilot. It is
not a general-purpose DAW clone and must keep the arrangement canvas visually
primary.

## Required product truths

1. JUCE is the only project/audio engine.
2. Tauri is the only desktop product shell.
3. Humans and AI use the same revision-checked command contract.
4. UI and AI snapshots come from one committed engine revision.
5. Every edit is auditable, undoable, and testable.
6. Model or network work never touches the realtime audio callback.

## Core workflow

```text
Open/import project
  -> arrange tracks, clips, notes, harmony, and instruments
  -> ask Copilot for a bounded change
  -> inspect the proposed musical intent
  -> execute one transactional command group
  -> hear or inspect the result
  -> keep, undo, or refine
  -> save/export/render
```

## Interface

- Center: arrangement and piano roll.
- Left: compact project/track context.
- Right: Copilot, current musical context, and concise change history.
- Hidden-by-default expert controls must not crowd the composition workflow.
- Tool call IDs and technical transport details are not user-facing content.

## Engine baseline

- project open/new/import/export;
- track, clip, note, selection, and transport commands;
- stable IDs and monotonic revision;
- undo/redo and command history;
- MIDI devices, audio device, plugin graph, presets, and render pipeline;
- atomic persistence and recovery.

## Copilot baseline

- chord/key/section and track-role summaries;
- melody-derived chord progressions with style-aware voicing;
- chord timeline syntax with beat duration and transitions;
- humanize, drums, bass, accompaniment, and re-orchestration plans;
- multi-track transaction planning and rollback;
- concise tool results written for musical decisions, not implementation
  diagnostics.
