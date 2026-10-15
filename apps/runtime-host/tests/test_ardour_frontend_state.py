from pathlib import Path

from reidom_runtime_host.ardour_frontend_state import build_ardour_frontend_state
from reidom_runtime_host.project_store import ProjectStore, project_to_selection


def test_ardour_frontend_state_projects_all_workspaces(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.demo_project()
    selection = project_to_selection(project)

    state = build_ardour_frontend_state(project, selection)

    assert state["schema"] == "reidom-ardour-frontend-state/v1"
    assert state["source"]["project_id"] == project["project_id"]
    assert state["transport"]["tempo"] == 126
    assert len(state["editor"]["routes"]) == len(project["tracks"])
    assert len(state["mixer"]["strips"]) == len(project["tracks"])
    assert state["mixer"]["master"]["track_id"] == "master"
    assert len(state["recorder"]["routes"]) == len(project["tracks"])
    assert state["cue_grid"]["scenes"]
    assert len(state["cue_grid"]["rows"]) == len(project["tracks"])


def test_ardour_frontend_state_exposes_selection_and_command_bridge(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.demo_project()
    clip_id = project["clips"][0]["clip_id"]
    project = store.apply_command(
        project["project_id"],
        {
            "schema": "reidom-command/v1",
            "command_id": "select-clip",
            "base_revision": project["revision"],
            "source": "user",
            "type": "selection.set",
            "payload": {"clip_ids": [clip_id]},
            "preview": False,
        },
    )

    state = build_ardour_frontend_state(project, project["selection"])
    selected_routes = [route for route in state["editor"]["routes"] if route["selected"]]

    assert selected_routes
    assert state["bridge"]["command_log"]["undo_depth"] == 1
    assert "clips.duplicate" in state["bridge"]["command_vocabulary"]
    assert "routes.set_state" in state["bridge"]["command_vocabulary"]
    assert "transport.set_state" in state["bridge"]["command_vocabulary"]
