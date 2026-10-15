# Architecture

## Product boundary

Reidom has one desktop host and two supervised product services:

- Tauri/Rust owns windows, filesystem UX, Runtime integration, process
  supervision, and presentation state.
- JUCE owns the project, audio/MIDI devices, transport, tracks, clips, notes,
  plugins, rendering, command history, undo, and redo.
- The AI tool service exposes ProjectEdit, forwarding schema-checked JSON
  transactions to JUCE. Native GrepJson reads the engine-published document.

Python is allowed only at the Agent Tool edge. It cannot own project state or
maintain an independent frontend snapshot.

## One command path

UI actions use `reidom-command/v2`. AI edits use `document.edit` with project ID,
revision and edit epoch. Both enter the same serialized JUCE owner, enforce the
current editor mode, and commit one undoable revision. AI batches are validated
before updating the project.

No mutation may bypass the command dispatcher. Audio callbacks never perform
network, JSON, model, file, or command-log work.

## One snapshot source

After a commit, JUCE creates one immutable snapshot bundle:

- `project_snapshot`: complete authoritative project state;
- `ui_snapshot`: editor projection;

These snapshots are for local UI and persistence. Project state is never
injected as a conversation-tail dynamic snapshot. AI explicitly reads
`projects/current.json` with GrepJson, including identity, revision, mode,
selection and song data. The role describes the contract without live facts.
Runtime conversation export remains for chat history, unrelated to project
context injection.

## Process protocol

The engine listens on loopback TCP port `47120`. A connection carries one
newline-terminated JSON request and receives one JSON response. Requests are
serialized, making revision checks and undo/redo deterministic. Tauri owns the
engine process lifetime; Agent tools connect as additional clients.

The desktop package pins Orbit Runtime `0.5.0` and installs its library,
configuration, and Skills beside the application. Tauri starts the MIDI Tool
service before connecting Runtime, restarts it after failure, and retries a
lost Runtime connection. Runtime events trigger a fresh JUCE snapshot pull, so
AI edits and manual edits converge on the same visible revision.

This protocol is a local product boundary, not a public Internet API. The next
hardening step is an authenticated session token plus event streaming for
incremental snapshots and meters.

## Modules

```text
engine/src/main.cpp
  Engine server
  ProjectState
  DomainCommand dispatcher
  Snapshot projection
  MIDI import/export
  AudioDeviceManager

apps/studio-web/src-tauri
  engine_client.rs       process + typed request adapter
  runtime_host.rs        Orbit Runtime 0.5.0 product adapter + reconnect
  tool_service.rs        packaged MIDI Tool service supervisor
  lib.rs                 Tauri IPC commands

services/midi-tools
  RuntimeHostClient      compatibility class name, JUCE TCP implementation
  harmony/chord modules  deterministic musical planning
  registered tools       AI command producers
```
