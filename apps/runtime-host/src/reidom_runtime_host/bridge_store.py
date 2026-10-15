from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _safe_adapter_id(adapter_id: str) -> str:
    normalized = adapter_id.strip().lower()
    if not normalized:
        raise ValueError("adapter_id is required")
    if any(not (char.isalnum() or char in {"-", "_"}) for char in normalized):
        raise ValueError(f"invalid adapter_id: {adapter_id}")
    return normalized


class BridgeStore:
    """Small file-backed exchange shared by the host, sidecars, and DAW adapters."""

    def __init__(self, root: Path):
        self.root = root
        self.commands_dir = root / "commands"
        self.root.mkdir(parents=True, exist_ok=True)
        self.commands_dir.mkdir(parents=True, exist_ok=True)

    @property
    def selection_path(self) -> Path:
        return self.root / "current-selection.json"

    def adapter_root(self, adapter_id: str) -> Path:
        return self.root / "adapters" / _safe_adapter_id(adapter_id)

    def adapter_selection_path(self, adapter_id: str) -> Path:
        return self.adapter_root(adapter_id) / "current-selection.json"

    def adapter_commands_dir(self, adapter_id: str) -> Path:
        return self.adapter_root(adapter_id) / "commands"

    def publish_selection(self, value: dict[str, Any], adapter_id: str = "ardour") -> None:
        if value.get("schema") != "reidom-midi-selection/v1":
            raise ValueError("expected reidom-midi-selection/v1")
        adapter_id = _safe_adapter_id(adapter_id)
        source = dict(value.get("source") or {})
        source.setdefault("daw_id", adapter_id)
        value = {**value, "source": source}
        self._write_json_atomic(self.adapter_selection_path(adapter_id), value)
        self._write_json_atomic(self.selection_path, value)

    def current_selection(self, adapter_id: str | None = None) -> dict[str, Any] | None:
        path = (
            self.selection_path if adapter_id is None else self.adapter_selection_path(adapter_id)
        )
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def queue_command(self, command: dict[str, Any], adapter_id: str | None = None) -> Path:
        command_id = str(command.get("command_id") or "").strip()
        if not command_id:
            raise ValueError("command_id is required")
        commands_dir = (
            self.commands_dir if adapter_id is None else self.adapter_commands_dir(adapter_id)
        )
        path = commands_dir / f"{command_id}.json"
        self._write_json_atomic(path, command)
        return path

    def commands(self, adapter_id: str | None = None) -> list[dict[str, Any]]:
        commands_dir = (
            self.commands_dir if adapter_id is None else self.adapter_commands_dir(adapter_id)
        )
        commands_dir.mkdir(parents=True, exist_ok=True)
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(commands_dir.glob("*.json"))
        ]

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
