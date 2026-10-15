# Source organization

Reidom keeps product UI, desktop orchestration, and the JUCE engine as separate ownership boundaries.

## Desktop UI (`apps/studio-web`)

- `app.js`: composition root. It wires services, state, controllers, and top-level commands.
- `src/features/arrangement`: arrangement rendering and timeline pointer interaction.
- `src/features/piano-roll`: piano-roll rendering, zoom, selection, note editing, and velocity interaction.
- `src/features/clips`: clip property editing.
- `src/features/effects`: per-track built-in effect controls.
- `src/features/project`: project dirty/autosave state.
- `src/features/settings`: audio and MIDI device settings.
- `src/features/workspace`: lightweight workspace actions.
- `src/shared`: UI utilities without DAW feature ownership.
- `src/styles`: ordered style layers; `styles.css` only composes them.

Feature modules may receive project state and command callbacks, but they must not invoke the JUCE sidecar directly. All project mutations continue through the shared command path.

## Tauri host (`apps/studio-web/src-tauri/src`)

- `lib.rs`: application composition and command registration only.
- `commands/engine.rs`: JUCE engine proxy, project IO, autosave, and history commands.
- `commands/ai.rs`: runtime conversation and AI snapshot commands.
- `commands/system.rs`: environment, tool-service status, and schema validation commands.
- `engine_client.rs`: sidecar process and transport ownership.
- `runtime_host.rs`: Agent Runtime connection.
- `state.rs`: application state.
- `tool_service.rs`: MIDI tool service lifecycle.

Every `#[tauri::command]` must be registered in `generate_handler!`. Shared state types must match the types registered with `manage`.

## JUCE engine (`engine/src`)

- `main.cpp`: process entry and command-line parsing only.
- `server`: local TCP request/response lifecycle and parent-process monitoring.
- `protocol`: JSON helpers and protocol conversion.
- `core/EngineTypes.h`: project, track, clip, note, transport, and render data.
- `core/ReidomEngine.*`: engine lifecycle, dispatch, snapshots, and history coordination.
- `core/ProjectCommands.cpp`: validated project mutations.
- `core/ProjectIO.cpp`: MIDI/project import-export, WAV rendering, and snapshot serialization.
- `audio/RealtimeAudio.cpp`: audio callback, transport clock, synthesis, monitoring, and MIDI recording.
- `audio/DeviceSettings.*`: audio/MIDI device discovery and configuration.
- `audio/TrackEffects.*`: built-in per-track effect processing.

The real-time audio callback must not gain blocking IO or project mutex access. UI and AI changes enter through the same serialized engine command contract.

## Size and dependency rules

- Entry files compose modules; they do not accumulate feature implementations.
- Extract a cohesive module before a source file grows beyond roughly 1,000 lines.
- Feature code may depend on `shared`; `shared` must not depend on a feature.
- Tauri commands may depend on host services; the JUCE engine must not depend on Tauri or web UI code.
- New engine mutations belong in `ProjectCommands.cpp`; new real-time processing belongs in `audio`.
- Preserve command-log, revision, undo/redo, and idempotency behavior when moving code.
