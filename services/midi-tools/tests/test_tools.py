from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("corework_agent_tool")

from reidom_midi_tools import main as tools


class FakeRuntimeHostClient:
    def __init__(self) -> None:
        self.commands: list[dict[str, Any]] = []
        self.undo_calls: list[str] = []
        self.redo_calls: list[str] = []
        self.command_log_calls: list[tuple[str, bool]] = []
        self.project = {
            "project_id": "demo-project",
            "revision": 7,
            "name": "Demo",
            "key_signature": "C major",
            "tempo_map": [{"bpm": 126}],
        }
        self.selection = {
            "selection_id": "sel-1",
            "tracks": [{"track_id": "lead", "notes": [{"note_id": "n1", "pitch": 60}]}],
            "selected_note_ids": ["n1"],
            "selected_clip_ids": [],
        }

    def context(self) -> dict[str, Any]:
        return {
            "active_project": self.project,
            "active_selection": self.selection,
            "adapters": [],
        }

    def run_command(
        self,
        project_id: str,
        command_type: str,
        payload: dict[str, Any],
        *,
        reason: str,
        command_id: str,
        base_revision: int,
    ) -> dict[str, Any]:
        self.commands.append(
            {
                "project_id": project_id,
                "type": command_type,
                "payload": payload,
                "reason": reason,
                "command_id": command_id,
                "base_revision": base_revision,
            }
        )
        self.project = {**self.project, "revision": base_revision + 1}
        return {"project": self.project, "selection": self.selection}

    def undo(self, project_id: str) -> dict[str, Any]:
        self.undo_calls.append(project_id)
        self.project = {**self.project, "revision": self.project["revision"] - 1}
        return {"project": self.project, "selection": self.selection}

    def redo(self, project_id: str) -> dict[str, Any]:
        self.redo_calls.append(project_id)
        self.project = {**self.project, "revision": self.project["revision"] + 1}
        return {"project": self.project, "selection": self.selection}

    def command_log(self, project_id: str, *, include_snapshots: bool = False) -> dict[str, Any]:
        self.command_log_calls.append((project_id, include_snapshots))
        return {
            "schema": "reidom-command-log/v1",
            "project_id": project_id,
            "revision": self.project["revision"],
            "undo_entries": [
                {
                    "index": 1,
                    "command_id": "cmd-ai-1",
                    "source": "ai",
                    "type": "notes.velocity",
                    "reason": "Soften the lead note.",
                }
            ],
            "redo_entries": [],
        }


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeRuntimeHostClient:
    client = FakeRuntimeHostClient()
    monkeypatch.setattr(
        tools.RuntimeHostClient,
        "from_tool_context",
        classmethod(lambda cls, ctx: client),
    )
    return client


def test_tool_module_does_not_expose_generic_run_command() -> None:
    assert not hasattr(tools, "midi_run_command")


def test_context_to_ai_is_a_short_musical_summary(fake_client: FakeRuntimeHostClient) -> None:
    output = tools.midi_get_context(object())

    assert output.error_code == tools.ToolErrorCode.OK
    assert output.to_ai == "当前工程《Demo》：1 条轨道，1 个音符，126 BPM，调性 C major。"
    assert "Midi" not in output.to_ai
    assert output.result["context"]["active_project"]["project_id"] == "demo-project"


def test_specific_note_tool_runs_auditable_command(fake_client: FakeRuntimeHostClient) -> None:
    output = tools.midi_set_note_velocity(
        object(),
        velocity=72,
        note_ids_json='["n1"]',
        reason="Soften the lead note before the answer phrase.",
    )

    assert output.error_code == tools.ToolErrorCode.OK
    assert output.result["type"] == "notes.velocity"
    assert fake_client.commands == [
        {
            "project_id": "demo-project",
            "type": "notes.velocity",
            "payload": {"note_ids": ["n1"], "velocity": 72},
            "reason": "Soften the lead note before the answer phrase.",
            "command_id": output.result["command_id"],
            "base_revision": 7,
        }
    ]
    assert output.result["command_id"].startswith("cmd-ai-")
    assert output.result["result_revision"] == 8


def test_specific_tool_requires_reason(fake_client: FakeRuntimeHostClient) -> None:
    output = tools.midi_move_notes(object(), delta_beats=0.25, note_ids_json='["n1"]')

    assert output.error_code == tools.ToolErrorCode.MISSING_ARGUMENT
    assert "require a musical reason" in output.to_ai
    assert fake_client.commands == []


def test_command_log_and_history_tools_use_active_project(fake_client: FakeRuntimeHostClient) -> None:
    log_output = tools.midi_get_command_log(object(), include_snapshots=True)
    undo_output = tools.midi_undo(object())
    redo_output = tools.midi_redo(object())

    assert log_output.error_code == tools.ToolErrorCode.OK
    assert fake_client.command_log_calls == [("demo-project", True)]
    assert undo_output.error_code == tools.ToolErrorCode.OK
    assert redo_output.error_code == tools.ToolErrorCode.OK
    assert fake_client.undo_calls == ["demo-project"]
    assert fake_client.redo_calls == ["demo-project"]
