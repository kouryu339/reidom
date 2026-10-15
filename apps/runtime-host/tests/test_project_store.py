from pathlib import Path

from reidom_runtime_host.project_store import (
    ProjectStore,
    midi_bytes_to_project,
    project_to_midi_bytes,
    project_to_selection,
)


def test_midi_bytes_to_project_creates_host_owned_state() -> None:
    project = midi_bytes_to_project("tiny.mid", _tiny_midi())

    assert project["schema"] == "reidom-project/v1"
    assert project["name"] == "tiny"
    assert len(project["tracks"]) == 1
    assert len(project["clips"]) == 1
    assert project["clips"][0]["notes"][0]["pitch"] == 60
    assert project["selection"]["schema"] == "reidom-midi-selection/v1"


def test_project_store_persists_active_project(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)

    project = store.import_midi("tiny.mid", _tiny_midi())

    assert store.active_project()["project_id"] == project["project_id"]
    assert store.project(project["project_id"])["name"] == "tiny"
    assert project_to_selection(project)["tracks"][0]["notes"][0]["pitch"] == 60


def test_demo_project_has_tracks_and_selection(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)

    project = store.demo_project()

    assert len(project["tracks"]) >= 4
    assert project["selection"]["tracks"]


def test_project_exports_midi_bytes(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.import_midi("tiny.mid", _tiny_midi())

    file_name, exported = store.export_midi(project["project_id"])

    assert file_name == "tiny.mid"
    assert exported.startswith(b"MThd")
    assert b"MTrk" in exported
    assert project_to_midi_bytes(project).startswith(b"MThd")


def test_project_commands_transpose_and_undo_redo(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.import_midi("tiny.mid", _tiny_midi())
    project_id = project["project_id"]
    note_id = project["clips"][0]["notes"][0]["note_id"]

    selected = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "select-1",
            "base_revision": project["revision"],
            "source": "user",
            "type": "selection.set",
            "payload": {"note_ids": [note_id]},
            "preview": False,
        },
    )
    transposed = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "transpose-1",
            "base_revision": selected["revision"],
            "source": "user",
            "type": "notes.transpose",
            "payload": {"semitones": 12},
            "preview": False,
        },
    )

    assert transposed["clips"][0]["notes"][0]["pitch"] == 72

    undone = store.undo(project_id)
    assert undone["clips"][0]["notes"][0]["pitch"] == 60

    redone = store.redo(project_id)
    assert redone["clips"][0]["notes"][0]["pitch"] == 72


def test_project_command_adds_note_and_selects_it(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.import_midi("tiny.mid", _tiny_midi())
    project_id = project["project_id"]

    updated = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "add-1",
            "base_revision": project["revision"],
            "source": "user",
            "type": "notes.add",
            "payload": {
                "track_id": project["tracks"][0]["track_id"],
                "pitch": 64,
                "start_beats": 1.25,
                "duration_beats": 0.5,
                "velocity": 88,
            },
            "preview": False,
        },
    )

    added = [note for note in updated["clips"][0]["notes"] if note["pitch"] == 64][0]
    assert added["start_beats"] == 1.25
    assert added["duration_beats"] == 0.5
    assert updated["selection"]["selected_note_ids"] == [added["note_id"]]


def test_project_command_updates_note_velocity(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.import_midi("tiny.mid", _tiny_midi())
    project_id = project["project_id"]
    note_id = project["clips"][0]["notes"][0]["note_id"]

    updated = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "velocity-1",
            "base_revision": project["revision"],
            "source": "user",
            "type": "notes.velocity",
            "payload": {"note_ids": [note_id], "velocity": 64},
            "preview": False,
        },
    )

    assert updated["clips"][0]["notes"][0]["velocity"] == 64
    assert updated["selection"]["selected_note_ids"] == [note_id]


def test_project_command_log_records_auditable_ai_steps(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.import_midi("tiny.mid", _tiny_midi())
    project_id = project["project_id"]
    note_id = project["clips"][0]["notes"][0]["note_id"]

    updated = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "ai-velocity-1",
            "base_revision": project["revision"],
            "source": "ai",
            "type": "notes.velocity",
            "payload": {"note_ids": [note_id], "velocity": 72},
            "reason": "Soften the lead note so it sits behind the next phrase.",
            "preview": False,
        },
    )

    command_log = store.command_log(project_id)
    [entry] = command_log["undo_entries"]

    assert command_log["revision"] == updated["revision"]
    assert entry["command_id"] == "ai-velocity-1"
    assert entry["source"] == "ai"
    assert entry["type"] == "notes.velocity"
    assert entry["payload"] == {"note_ids": [note_id], "velocity": 72}
    assert entry["base_revision"] == project["revision"]
    assert entry["result_revision"] == updated["revision"]
    assert "Soften the lead note" in entry["reason"]
    assert "before" not in entry
    assert "after" not in entry

    replay_log = store.command_log(project_id, include_snapshots=True)
    replay_entry = replay_log["undo_entries"][0]
    assert replay_entry["before"]["revision"] == project["revision"]
    assert replay_entry["after"]["revision"] == updated["revision"]


def test_project_command_can_clear_selection(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.import_midi("tiny.mid", _tiny_midi())
    project_id = project["project_id"]
    note_id = project["clips"][0]["notes"][0]["note_id"]
    selected = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "select-then-clear-1",
            "base_revision": project["revision"],
            "source": "user",
            "type": "selection.set",
            "payload": {"note_ids": [note_id]},
            "preview": False,
        },
    )

    cleared = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "clear-selection-1",
            "base_revision": selected["revision"],
            "source": "user",
            "type": "selection.set",
            "payload": {"note_ids": [], "clip_ids": []},
            "preview": False,
        },
    )

    assert cleared["selection"]["selected_note_ids"] == []
    assert cleared["selection"]["selected_clip_ids"] == []


def test_project_command_duplicates_selected_notes(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.import_midi("tiny.mid", _tiny_midi())
    project_id = project["project_id"]
    note_id = project["clips"][0]["notes"][0]["note_id"]

    updated = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "duplicate-1",
            "base_revision": project["revision"],
            "source": "user",
            "type": "notes.duplicate",
            "payload": {"note_ids": [note_id], "delta_beats": 0.5},
            "preview": False,
        },
    )

    assert len(updated["clips"][0]["notes"]) == 2
    duplicated_id = updated["selection"]["selected_note_ids"][0]
    duplicated = [note for note in updated["clips"][0]["notes"] if note["note_id"] == duplicated_id][0]
    assert duplicated["start_beats"] == 0.5
    assert duplicated["pitch"] == 60


def test_project_commands_move_and_resize_clips(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.import_midi("tiny.mid", _tiny_midi())
    project_id = project["project_id"]
    clip_id = project["clips"][0]["clip_id"]

    moved = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "clip-move-1",
            "base_revision": project["revision"],
            "source": "user",
            "type": "clips.move",
            "payload": {"clip_ids": [clip_id], "delta_beats": 1},
            "preview": False,
        },
    )
    assert moved["clips"][0]["start_beats"] == 1
    assert moved["selection"]["selected_clip_ids"] == [clip_id]

    resized = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "clip-resize-1",
            "base_revision": moved["revision"],
            "source": "user",
            "type": "clips.resize",
            "payload": {"clip_ids": [clip_id], "delta_beats": 2},
            "preview": False,
        },
    )
    assert resized["clips"][0]["duration_beats"] == 3
    assert resized["selection"]["selected_clip_ids"] == [clip_id]


def test_project_command_duplicates_clips_with_new_note_ids(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.import_midi("tiny.mid", _tiny_midi())
    project_id = project["project_id"]
    clip_id = project["clips"][0]["clip_id"]
    original_note_id = project["clips"][0]["notes"][0]["note_id"]

    updated = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "clip-duplicate-1",
            "base_revision": project["revision"],
            "source": "ai",
            "type": "clips.duplicate",
            "payload": {"clip_ids": [clip_id], "delta_beats": 4},
            "reason": "Repeat the phrase in the next bar group.",
            "preview": False,
        },
    )

    duplicated_id = updated["selection"]["selected_clip_ids"][0]
    duplicated = [clip for clip in updated["clips"] if clip["clip_id"] == duplicated_id][0]

    assert len(updated["clips"]) == 2
    assert duplicated["start_beats"] == 4
    assert duplicated["notes"][0]["note_id"] != original_note_id
    assert duplicated_id in updated["tracks"][0]["clip_ids"]


def test_project_commands_update_route_and_transport_state(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.demo_project()
    project_id = project["project_id"]
    track_id = project["tracks"][0]["track_id"]

    routed = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "route-state-1",
            "base_revision": project["revision"],
            "source": "user",
            "type": "routes.set_state",
            "payload": {
                "track_id": track_id,
                "state": {"record": True, "monitor": True, "mute": True, "volume": 0.5},
            },
            "preview": False,
        },
    )
    route = [track for track in routed["tracks"] if track["track_id"] == track_id][0]
    assert route["arm"] is True
    assert route["monitor"] is True
    assert route["mute"] is True
    assert route["volume"] == 0.5

    transported = store.apply_command(
        project_id,
        {
            "schema": "reidom-command/v1",
            "command_id": "transport-state-1",
            "base_revision": routed["revision"],
            "source": "user",
            "type": "transport.set_state",
            "payload": {"playing": True, "loop": True, "tempo": 132},
            "preview": False,
        },
    )
    assert transported["transport"]["playing"] is True
    assert transported["transport"]["loop"] is True
    assert transported["tempo_map"][0]["bpm"] == 132

    command_log = store.command_log(project_id)
    assert [entry["type"] for entry in command_log["undo_entries"][-2:]] == [
        "routes.set_state",
        "transport.set_state",
    ]

    undone = store.undo(project_id)
    assert undone["transport"]["playing"] is False
    assert undone["transport"]["loop"] is False


def _tiny_midi() -> bytes:
    header = b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big")
    header += (1).to_bytes(2, "big") + (480).to_bytes(2, "big")
    events = bytes(
        [
            0x00,
            0xFF,
            0x03,
            0x04,
            *b"Lead",
            0x00,
            0x90,
            0x3C,
            0x64,
            0x83,
            0x60,
            0x80,
            0x3C,
            0x00,
            0x00,
            0xFF,
            0x2F,
            0x00,
        ]
    )
    return header + b"MTrk" + len(events).to_bytes(4, "big") + events
