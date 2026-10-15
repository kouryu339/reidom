# Reidom Engine

`reidom-engine` is the only project-state and audio-engine owner. It is a
headless JUCE 9 process; Tauri owns windows and product UI, while Agent tools
and the UI both submit the same `reidom-command/v2` contract to this process.

The engine listens on `127.0.0.1:47120` by default. Each connection carries one
UTF-8 JSON request and receives one JSON response. Requests are serialized by
the engine, so project revisions, undo/redo, UI snapshots, and AI snapshots
commit atomically.

Build on Windows from a Visual Studio developer environment:

```powershell
& "D:\visualS\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" `
  -S engine -B build\engine -G Ninja `
  -DCMAKE_MAKE_PROGRAM="D:\visualS\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"
& "D:\visualS\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" `
  --build build\engine --config Release
```

Run `reidom-engine.exe --self-test` for the command/snapshot/undo smoke test.
