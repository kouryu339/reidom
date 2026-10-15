# Reidom Studio

This is the Tauri v2 product shell for the Reidom JUCE engine.

The web layer does not call a Python project server. In the desktop app it uses
registered Tauri commands such as `engine_snapshot`, `engine_apply_command`,
`engine_undo`, and `engine_redo`. Browser-only mode is a visual preview and has
no project engine.

Run:

```powershell
..\..\scripts\build-juce-engine.ps1
npm install
npm run tauri:dev
```

`npm run tauri:build` stages the pinned Orbit Runtime `0.5.0`, the JUCE engine,
the MIDI Tool service, configuration, and Reidom Skills into the installer.
The desktop host supervises both native services and reconnects Runtime after a
connection loss.
