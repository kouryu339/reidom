from __future__ import annotations

import json
import os
import socket
from typing import Any


class RuntimeHostError(RuntimeError):
    pass


class RuntimeHostClient:
    """Compatibility name for the JUCE engine command client."""

    def __init__(self, endpoint: str):
        host, separator, port = endpoint.rpartition(":")
        if not separator or not host or not port.isdigit():
            raise ValueError(f"invalid JUCE engine endpoint: {endpoint}")
        self.host = host
        self.port = int(port)

    @classmethod
    def from_tool_context(cls, ctx: Any) -> RuntimeHostClient:
        return cls(_rpc_base_url(ctx))

    def context(self) -> dict[str, Any]:
        snapshot = self._request({"method": "snapshot.get"})
        ui = snapshot.get("ui_snapshot") or {}
        return {
            "schema": "reidom-console-context/v2",
            "snapshot_bundle": snapshot,
            "active_project": ui.get("project"),
            "active_selection": ui.get("selection"),
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
        result = self._request(
            {
                "method": "command.apply",
                "command": {
                    "schema": "reidom-command/v2",
                    "command_id": command_id,
                    "idempotency_key": command_id,
                    "project_id": project_id,
                    "base_revision": base_revision,
                    "source": "ai",
                    "type": command_type,
                    "payload": payload,
                    "reason": reason,
                    "preview": False,
                },
            },
        )
        snapshot = result.get("snapshot") or {}
        ui = snapshot.get("ui_snapshot") or {}
        return {
            "project": ui.get("project") or {},
            "selection": ui.get("selection") or {},
            "snapshot_bundle": snapshot,
            "command_result": result,
        }

    def undo(self, project_id: str) -> dict[str, Any]:
        del project_id
        return self._project_response(self._request({"method": "history.undo"}))

    def redo(self, project_id: str) -> dict[str, Any]:
        del project_id
        return self._project_response(self._request({"method": "history.redo"}))

    def command_log(
        self,
        project_id: str,
        *,
        include_snapshots: bool = False,
    ) -> dict[str, Any]:
        del project_id, include_snapshots
        return self._request({"method": "history.get"})

    def _request(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            with socket.create_connection((self.host, self.port), timeout=10) as connection:
                connection.sendall(json.dumps(request).encode("utf-8") + b"\n")
                connection.shutdown(socket.SHUT_WR)
                chunks: list[bytes] = []
                while True:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
        except (OSError, TimeoutError) as exc:
            raise RuntimeHostError(f"JUCE engine is unavailable: {exc}") from exc
        try:
            response = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeHostError(f"JUCE engine returned invalid JSON: {exc}") from exc
        if response.get("ok") is True:
            result = response.get("result")
            return result if isinstance(result, dict) else {}
        error = response.get("error") or {}
        raise RuntimeHostError(str(error.get("message") or "JUCE engine rejected the request"))

    @staticmethod
    def _project_response(snapshot: dict[str, Any]) -> dict[str, Any]:
        ui = snapshot.get("ui_snapshot") or {}
        return {
            "project": ui.get("project") or {},
            "selection": ui.get("selection") or {},
            "snapshot_bundle": snapshot,
        }


def _rpc_base_url(ctx: Any) -> str:
    host_context = _host_context(ctx)
    reidom_context = host_context.get("reidom") if isinstance(host_context, dict) else None
    if isinstance(reidom_context, dict):
        value = str(reidom_context.get("engine_endpoint") or "").strip()
        if value:
            return value
    return os.getenv("REIDOM_ENGINE_ENDPOINT", "127.0.0.1:47120")


def _host_context(ctx: Any) -> dict[str, Any]:
    for name in ("host_context", "host_context_json"):
        value = getattr(ctx, name, None)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}
