from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable


class RuntimeAdapter:
    """Thin product adapter over ai-framework's shared Python Runtime SDK."""

    def __init__(self, library_path: Path, data_dir: Path):
        from corework_runtime import Runtime

        self._runtime_type = Runtime
        self._library_path = library_path
        self._data_dir = data_dir
        self._runtime: Any = None
        self._stop = threading.Event()
        self._event_thread: threading.Thread | None = None

    def start(
        self,
        resources_path: Path,
        llm_path: Path,
        cluster_path: Path,
        on_event: Callable[[dict[str, Any] | str], None] | None = None,
    ) -> None:
        runtime = self._runtime_type(
            self._library_path,
            {
                "schema": "agent-runtime-create-options/v1",
                "log_level": "info",
                "language": "zh-CN",
                "restore_policy": "strict",
                "data_dir": str(self._data_dir),
            },
        )
        self._runtime = runtime
        resolved_llm = self._resolve_llm(llm_path)
        runtime.invoke("runtime.register_resources", {"input": str(resources_path)})
        runtime.invoke("runtime.register_llm", {"input": str(resolved_llm)})
        runtime.invoke("runtime.register_agent_cluster", {"input": str(cluster_path)})
        runtime.start()
        self._stop.clear()
        self._event_thread = threading.Thread(
            target=self._pump_events,
            args=(on_event,),
            name="reidom-runtime-events",
            daemon=True,
        )
        self._event_thread.start()

    def spawn_conversation(self) -> dict[str, Any]:
        result = self._require_runtime().invoke(
            "conversation.spawn",
            {
                "schema": "agent-runtime-conversation-spawn/v1",
                "cluster_id": "reidom-music",
            },
        )
        return result if isinstance(result, dict) else {}

    def send_message(self, conversation_id: str, content: str) -> dict[str, Any]:
        result = self._require_runtime().invoke(
            "conversation.send_message",
            {"conversation_id": conversation_id, "content": content},
        )
        return result if isinstance(result, dict) else {}

    def close(self) -> None:
        if self._runtime is None:
            return
        self._stop.set()
        if self._event_thread is not None:
            self._event_thread.join(timeout=1)
        self._runtime.close()
        self._runtime = None

    def _pump_events(self, on_event: Callable[[dict[str, Any] | str], None] | None) -> None:
        for event in self._require_runtime().events(timeout_ms=250, stop=self._stop):
            if on_event is not None:
                on_event(event)

    def _require_runtime(self) -> Any:
        if self._runtime is None:
            raise RuntimeError("agent runtime is not started")
        return self._runtime

    def _resolve_llm(self, path: Path) -> Path:
        target = self._data_dir / "llm-providers.resolved.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            example_path = path.with_name("llm-providers.example.json")
            if example_path.exists():
                path = example_path
            else:
                target.write_text(
                    json.dumps(_empty_llm_registration(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return target
        text = path.read_text(encoding="utf-8-sig")
        replacements = {
            "${LLM_API_KEY}": os.getenv("LLM_API_KEY", ""),
            "${LLM_BASE_URL}": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            "${LLM_MODEL_ID}": os.getenv("LLM_MODEL_ID", "gpt-4.1-mini"),
        }
        for source, replacement in replacements.items():
            text = text.replace(source, replacement)
        value = json.loads(text)
        if (
            value.get("schema") == "agent-runtime-provider-config/v1"
            and not value.get("id")
        ):
            value["id"] = "reidom-runtime-host-llm"
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return target


def _empty_llm_registration() -> dict[str, Any]:
    return {
        "schema": "agent-runtime-llm-registration/v1",
        "id": "reidom-runtime-host-llm",
        "providers": [],
        "current_model_uid": None,
    }
