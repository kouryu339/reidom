from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_registered_arranger_uses_only_json_project_tools() -> None:
    registration = json.loads((ROOT / "config" / "resources.json").read_text(encoding="utf-8"))
    profile = next(
        item for item in registration["agents"]["profiles"] if item["id"] == "reidom.arranger"
    )
    skill_root = (ROOT / "config" / registration["skills"]["root_dir"]).resolve()
    role = skill_root / "role" / profile["role"] / "SKILL.md"
    frontmatter = _frontmatter(role.read_text(encoding="utf-8"))

    assert frontmatter["name"] == profile["role"]
    assert frontmatter["kind"] == "role"
    assert frontmatter["description"].strip()
    assert ast.literal_eval(frontmatter["tools"]) == ["GrepJson", "ProjectEdit"]
    assert profile["features"] == []
    assert registration["skills"]["builtin_system"] is False
    assert not (skill_root / "feature" / "midi_arrangement" / "SKILL.md").exists()


def test_desktop_bundle_includes_registered_skill_root() -> None:
    desktop_root = ROOT / "apps" / "studio-web" / "src-tauri"
    desktop = json.loads((desktop_root / "tauri.conf.json").read_text(encoding="utf-8"))
    resources = desktop["bundle"]["resources"]
    skill_source = next(source for source, target in resources.items() if target == "skills/")

    assert (desktop_root / skill_source).resolve() == (ROOT / "skills").resolve()


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    assert lines[0] == "---", "SKILL.md must start with YAML frontmatter"
    end = lines.index("---", 1)
    fields = dict(line.split(":", 1) for line in lines[1:end] if line.strip())
    return {key: value.strip() for key, value in fields.items()}
