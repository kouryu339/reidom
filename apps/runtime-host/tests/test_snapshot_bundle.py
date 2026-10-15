from __future__ import annotations

import json
from pathlib import Path

from reidom_runtime_host.project_store import ProjectStore
from reidom_runtime_host.snapshot_bundle import build_snapshot_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_snapshot_bundle_projects_one_committed_revision(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.demo_project()

    bundle = build_snapshot_bundle(project, project["selection"])

    assert bundle["schema"] == "reidom-snapshot-bundle/v2"
    assert bundle["source"]["owner"] == "project-engine"
    assert bundle["source_revision"] == project["revision"]
    assert bundle["project_snapshot"]["source_revision"] == project["revision"]
    assert bundle["ui_snapshot"]["source_revision"] == project["revision"]
    assert bundle["ai_snapshot"]["source_revision"] == project["revision"]
    assert bundle["ui_snapshot"]["project"]["revision"] == project["revision"]
    assert f"Revision: {project['revision']}" in bundle["ai_snapshot"]["fields"]["reidom.project"]


def test_snapshot_bundle_normalizes_stale_selection_to_project_revision(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.demo_project()
    selection = dict(project["selection"])
    selection["revision"] = 0
    selection["project_id"] = "stale-project"
    selection["selected_note_ids"] = ["ghost-note"]

    bundle = build_snapshot_bundle(project, selection)

    normalized = bundle["project_snapshot"]["selection"]
    assert normalized["project_id"] == project["project_id"]
    assert normalized["revision"] == project["revision"]
    assert normalized["selected_note_ids"] == project["selection"]["selected_note_ids"]
    assert bundle["ui_snapshot"]["selection"] == normalized
    assert bundle["ai_snapshot"]["source_revision"] == normalized["revision"]


def test_ui_snapshot_does_not_duplicate_command_history_snapshots(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.demo_project()
    project = store.apply_command(
        project["project_id"],
        {
            "schema": "reidom-command/v1",
            "command_id": "select-one",
            "base_revision": project["revision"],
            "source": "user",
            "type": "selection.set",
            "payload": {"note_ids": [project["clips"][0]["notes"][0]["note_id"]]},
            "preview": False,
        },
    )

    bundle = build_snapshot_bundle(project, project["selection"])
    ui_project = bundle["ui_snapshot"]["project"]

    assert ui_project["undo_stack"] == []
    assert ui_project["redo_stack"] == []
    assert bundle["ui_snapshot"]["history"]["undo_depth"] == 1
    assert "before" not in json.dumps(bundle["ui_snapshot"])


def test_protocol_examples_match_checked_root_contracts() -> None:
    pairs = [
        ("command.v2.schema.json", "command-v2.json"),
        ("command-result.v2.schema.json", "command-result-v2.json"),
        ("engine-event.v2.schema.json", "engine-event-v2.json"),
        ("snapshot-bundle.v2.schema.json", "snapshot-bundle-v2.json"),
    ]
    for schema_name, example_name in pairs:
        schema = _read_json(REPO_ROOT / "protocol" / schema_name)
        example = _read_json(REPO_ROOT / "protocol" / "examples" / example_name)
        assert set(schema["required"]) <= set(example)
        assert set(example) <= set(schema["properties"])
        assert example["schema"] == schema["properties"]["schema"]["const"]


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
