from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    bridge_dir: Path
    runtime_library: Path | None
    daw_manifest_path: Path
    resources_path: Path
    llm_path: Path
    cluster_path: Path
    host: str
    port: int
    cors_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        root = _repo_root()
        library = os.getenv("AGENT_RUNTIME_LIBRARY", "").strip()
        bridge_dir = Path(os.getenv("REIDOM_BRIDGE_DIR", root / "data" / "bridge"))
        return cls(
            repo_root=root,
            bridge_dir=bridge_dir,
            runtime_library=Path(library) if library else None,
            daw_manifest_path=root / "integrations" / "adapters.json",
            resources_path=root / "config" / "resources.json",
            llm_path=root / "config" / "llm-providers.json",
            cluster_path=root / "config" / "agent-cluster.json",
            host=os.getenv("REIDOM_HOST", "127.0.0.1"),
            port=int(os.getenv("REIDOM_PORT", "47110")),
            cors_origins=tuple(
                origin.strip()
                for origin in os.getenv(
                    "REIDOM_CORS_ORIGINS",
                    "http://127.0.0.1:47110,http://localhost:47110,"
                    "http://127.0.0.1:5173,http://localhost:5173",
                ).split(",")
                if origin.strip()
            ),
        )
