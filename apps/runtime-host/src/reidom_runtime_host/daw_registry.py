from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DawAdapterRegistry:
    """Reads the product-facing DAW adapter manifest.

    The manifest is intentionally data-only. Real DAW integration code can live in
    Lua, Max for Live, Java controller extensions, Python scripts, or a C++ fork,
    while the host and frontend keep one stable view of available adapters.
    """

    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path

    def manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {"schema": "reidom-daw-adapters/v1", "adapters": []}
        value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if value.get("schema") != "reidom-daw-adapters/v1":
            raise ValueError("expected reidom-daw-adapters/v1")
        value.setdefault("adapters", [])
        return value

    def adapters(self) -> list[dict[str, Any]]:
        return sorted(
            self.manifest()["adapters"],
            key=lambda adapter: (adapter.get("priority", 999), adapter.get("name", "")),
        )

    def adapter(self, adapter_id: str) -> dict[str, Any] | None:
        normalized = adapter_id.strip().lower()
        for adapter in self.adapters():
            if adapter.get("id") == normalized:
                return adapter
        return None
