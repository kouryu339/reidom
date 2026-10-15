# Reidom

Reidom is a lightweight AI-native MIDI arranging application with one product
architecture:

```text
Tauri UI or Agent Tool
        |
        | reidom-command/v2
        v
JUCE Engine (authoritative project owner)
        |
        +-- audio/MIDI devices and transport
        +-- project, tracks, clips, notes, plugins
        +-- command log, undo, redo, import, export
        +-- one committed revision
                    |
                    +-- UI snapshot
                    +-- AI snapshot
```

There is no Ardour compatibility path. Manual editing and AI editing use the
same command dispatcher, and both snapshots are published from the same JUCE
project revision.

## Repository map

```text
engine/                 Headless JUCE 9 project/audio engine
apps/studio-web/        Tauri v2 product shell and lightweight arranger UI
services/midi-tools/    Agent Tool surface speaking directly to the JUCE engine
protocol/               Versioned command/result/event/snapshot contracts
skills/                 Arranger role and MIDI arrangement behavior
config/                 Runtime resources, providers, and Agent cluster inputs
third_party/JUCE/        Pinned JUCE 9.0.0 source dependency
```

## Build the JUCE engine

```powershell
.\scripts\setup-juce.ps1
.\scripts\build-juce-engine.ps1
```

The engine binary supports a local smoke test:

```powershell
.\build\engine-ninja\reidom-engine_artefacts\Release\reidom-engine.exe --self-test
```

## Run the desktop app

Windows development requires Visual Studio C++ tools/CMake, Rust, Node.js, and
Python 3.11+ with PyInstaller and the MIDI Tool dependencies. Set `AI_FRAMEWORK_DIR`
to your Orbit Runtime 0.5.0 checkout (or pass `-AiFrameworkDir` to the build scripts).
No developer-specific dependency or Python paths are hard-coded.

Before the first desktop run, prepare the runtime and MIDI Tool sidecar from the
repository root with `./scripts/stage-desktop-runtime.ps1`. You must build the
JUCE engine above first. No compiled runtime binaries are committed here.

```powershell
cd apps\studio-web
npm install
npm run tauri:dev
```

Tauri starts and supervises the JUCE engine on `127.0.0.1:47120`. The MIDI Tool
service is also supervised by Tauri and connects to the same endpoint. Orbit
Runtime `0.5.0`, the tool service, runtime configuration, and Skills are staged
automatically for desktop builds:

```powershell
npm run tauri:build
```

For standalone tool development, run `.\scripts\dev-midi-tools.ps1` from the
repository root.

See [architecture](docs/architecture.md), [product requirements](docs/product-requirements.md),
and [licensing](docs/licensing.md).

## License

Reidom-authored source is licensed under [Apache-2.0](LICENSE).
Third-party components retain their own licenses. In particular, JUCE uses
AGPLv3 or a JUCE commercial license; this repository is not an Apache-only grant
for combined JUCE builds. See [licensing](docs/licensing.md) and [NOTICE](NOTICE).
