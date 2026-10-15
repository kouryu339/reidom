from pathlib import Path

from reidom_runtime_host.bridge_store import BridgeStore


def test_selection_round_trip(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path)
    selection = {
        "schema": "reidom-midi-selection/v1",
        "selection_id": "selection-1",
        "project_id": "project-1",
        "revision": 1,
        "tracks": [],
    }

    store.publish_selection(selection)

    saved = store.current_selection(adapter_id="ardour")
    assert saved is not None
    assert saved["selection_id"] == selection["selection_id"]
    assert saved["source"]["daw_id"] == "ardour"


def test_selection_is_scoped_by_adapter(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path)

    store.publish_selection(
        {
            "schema": "reidom-midi-selection/v1",
            "selection_id": "reaper-selection",
            "project_id": "project-1",
            "revision": 1,
            "tracks": [],
        },
        adapter_id="reaper",
    )

    assert store.current_selection(adapter_id="ardour") is None
    assert store.current_selection(adapter_id="reaper")["selection_id"] == "reaper-selection"
