# Roadmap

## M0: JUCE cutover

- [x] Pin JUCE 9.0.0 and compile a headless engine.
- [x] Make JUCE the authoritative project and snapshot owner.
- [x] Implement v2 revision-checked commands, undo, redo, MIDI import/export,
  audio-device initialization, and a self-test.
- [x] Make Tauri start and call the JUCE engine directly.
- [x] Make MIDI Agent Tools call the same engine endpoint.
- [x] Package Orbit Runtime 0.5.0, configuration, Skills, and the MIDI Tool
  service with the desktop installer.
- [x] Supervise the tool service, retry Runtime connections, and refresh the UI
  from JUCE after AI-side changes.
- [x] Remove Ardour source, sidecar, native integration, Skill, scripts, and
  Runtime registration.

## M1: production engine

- Split the prototype engine file into project, command, snapshot, audio,
  plugin, persistence, and transport modules.
- Persist projects atomically and recover the last clean revision.
- Add VST3/AU discovery, sandbox policy, fixed logical instrument presets, and
  missing-plugin recovery.
- Add real transport playback, scheduling, metronome, loop, offline render, and
  latency compensation.
- Add authenticated event streaming for meters and snapshot deltas.

## M2: arranging copilot

- Move chord analysis, chord timelines, harmony planning, humanize, drums,
  bass, accompaniment, and orchestration plans onto JUCE project IDs.
- Execute multi-track plans transactionally as one command group.
- Add deterministic preflight, postcondition checks, and automatic rollback.
- Add render-before/render-after A/B selection where objective analysis is
  possible.

## M3: productization

- Signed Tauri/JUCE installer and updates.
- Project migration and crash recovery.
- Privacy controls, opt-in diagnostics, and support bundles.
- JUCE commercial licensing and third-party asset/license verification.
