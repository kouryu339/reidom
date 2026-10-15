from __future__ import annotations

import json
from pathlib import Path

from reidom_runtime_host.runtime_adapter import RuntimeAdapter


def test_resolve_llm_uses_empty_registration_when_config_is_missing(tmp_path: Path) -> None:
    adapter = RuntimeAdapter.__new__(RuntimeAdapter)
    adapter._data_dir = tmp_path

    resolved = adapter._resolve_llm(tmp_path / "missing-llm.json")

    value = json.loads(resolved.read_text(encoding="utf-8"))
    assert value["schema"] == "agent-runtime-llm-registration/v1"
    assert value["providers"] == []
    assert value["current_model_uid"] is None


def test_resolve_llm_keeps_example_model_registration_without_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = RuntimeAdapter.__new__(RuntimeAdapter)
    adapter._data_dir = tmp_path
    source = tmp_path / "llm-providers.json"
    source.write_text(
        json.dumps(
            {
                "schema": "agent-runtime-llm-registration/v1",
                "id": "reidom-llm",
                "providers": [{"api_key": "${LLM_API_KEY}"}],
                "current_model_uid": 1001,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    resolved = adapter._resolve_llm(source)

    value = json.loads(resolved.read_text(encoding="utf-8"))
    assert value["providers"] == [{"api_key": ""}]
    assert value["current_model_uid"] == 1001


def test_resolve_llm_falls_back_to_example_when_main_config_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = RuntimeAdapter.__new__(RuntimeAdapter)
    adapter._data_dir = tmp_path / "runtime"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "llm-providers.example.json").write_text(
        json.dumps(
            {
                "schema": "agent-runtime-llm-registration/v1",
                "id": "reidom-llm",
                "providers": [{"api_key": "${LLM_API_KEY}"}],
                "current_model_uid": 1001,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    resolved = adapter._resolve_llm(config_dir / "llm-providers.json")

    value = json.loads(resolved.read_text(encoding="utf-8"))
    assert value["providers"] == [{"api_key": ""}]
    assert value["current_model_uid"] == 1001
