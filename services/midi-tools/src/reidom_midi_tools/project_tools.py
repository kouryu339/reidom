"""Small AI surface. The engine owns validation, authority and transactions."""
from __future__ import annotations

import json
import os
from corework_agent_tool import AIOutput, ToolErrorCode, register_tool, serve
from .runtime_rpc import RuntimeHostClient, RuntimeHostError


@register_tool(
    name="ProjectEdit",
    description="Atomically edit the current music project with schema-checked JSON. Read projects/current.json using native GrepJson first. Manual editing blocks writes.",
    parameters=[{"name":"edit_json", "param_type":"String", "required":True,
        "description":"JSON object: project_id, expected_revision, edit_epoch, request_id, reason, changes. changes: merge target song fields {name,tempo}; upsert target tracks/clips/notes items [{id,...changed fields}]; remove target tracks/clips/notes ids [id]. Notes target requires clip_id. New objects require all fields. Times are absolute quarter-note beats. Read projects/schema.json for fields."}],
    outputs=[{"name":"result", "field_type":"Object", "description":"Committed project revision or structured rejection."}],
    readonly=False, destructive=False, idempotent=True, open_world=False, secret=False,
)
def project_edit(ctx, edit_json: str) -> AIOutput:
    try:
        if len(edit_json.encode("utf-8")) > 1_000_000:
            raise ValueError("Edit exceeds 1 MB; split by musical phrase")
        request = json.loads(edit_json)
        allowed = {"project_id", "expected_revision", "edit_epoch", "request_id", "reason", "changes"}
        if not isinstance(request, dict) or set(request) != allowed:
            raise ValueError("Expected exactly: project_id, expected_revision, edit_epoch, request_id, reason, changes")
        result = RuntimeHostClient.from_tool_context(ctx)._request({**request, "method":"document.edit"})
        return AIOutput(result=result, to_ai=f"已提交 r{result['revision']}，可撤销。", error_code=ToolErrorCode.OK)
    except (ValueError, TypeError, RuntimeHostError) as error:
        return AIOutput(result={"error":str(error)}, to_ai=f"未提交：{error}。不要递增 revision。手动模式时停止写入；版本冲突时用 GrepJson 重新读取。", error_code=ToolErrorCode.INVALID_ARGUMENT)


def main() -> None:
    serve(host=os.getenv("REIDOM_MIDI_TOOL_HOST", "127.0.0.1"), port=int(os.getenv("REIDOM_MIDI_TOOL_PORT", "50120")))


if __name__ == "__main__":
    main()
