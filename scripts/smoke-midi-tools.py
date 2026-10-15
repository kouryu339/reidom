from __future__ import annotations

import argparse
import importlib
import json
import socket
import sys
import tempfile
from pathlib import Path

import grpc
from grpc_tools import protoc


def engine_request(endpoint: str, request: dict) -> dict:
    host, port = endpoint.rsplit(":", 1)
    with socket.create_connection((host, int(port)), timeout=10) as connection:
        connection.sendall(json.dumps(request).encode("utf-8") + b"\n")
        connection.shutdown(socket.SHUT_WR)
        payload = b""
        while chunk := connection.recv(65536):
            payload += chunk
    response = json.loads(payload.decode("utf-8"))
    if response.get("ok") is not True:
        raise RuntimeError(response)
    return response["result"]


def proto_modules(proto_path: Path):
    output = Path(tempfile.mkdtemp(prefix="reidom-tool-smoke-"))
    result = protoc.main(
        [
            "grpc_tools.protoc",
            f"-I{proto_path.parent}",
            f"--python_out={output}",
            f"--grpc_python_out={output}",
            str(proto_path),
        ]
    )
    if result != 0:
        raise RuntimeError("failed to compile tool protocol")
    sys.path.insert(0, str(output))
    return (
        importlib.import_module("corework_agent_tool_v1_pb2"),
        importlib.import_module("corework_agent_tool_v1_pb2_grpc"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="127.0.0.1:47120")
    parser.add_argument("--tools", default="127.0.0.1:50120")
    parser.add_argument("--proto", type=Path, required=True)
    args = parser.parse_args()

    engine_request(args.engine, {"method": "project.demo"})
    pb2, pb2_grpc = proto_modules(args.proto)
    with grpc.insecure_channel(args.tools) as channel:
        grpc.channel_ready_future(channel).result(timeout=10)
        client = pb2_grpc.AgentToolServiceStub(channel)
        tools = client.ListTools(
            pb2.ListToolsRequest(
                runtime_version="0.4.6",
                accepted_schema=["corework-agent-tool/v1"],
            ),
            timeout=10,
        )
        names = {tool.name for tool in tools.tools}
        if "MidiGetContext" not in names or "MidiGeneratePianoHarmony" not in names:
            raise RuntimeError(f"required tools missing: {sorted(names)}")
        request = pb2.ToolStreamMessage(
            call_id="smoke-context",
            execute_request=pb2.ExecuteRequest(
                tool_name="MidiGetContext",
                args_json="{}",
                host_context_json=json.dumps({"reidom": {"engine_endpoint": args.engine}}),
            ),
        )
        responses = list(client.Execute(iter([request]), timeout=15))
        output = next((item.ai_output for item in responses if item.HasField("ai_output")), None)
        if output is None or output.error_code != 1:
            raise RuntimeError(f"MidiGetContext failed: {responses}")
        context = json.loads(output.result_json)["context"]
        project = context.get("active_project") or {}
        if not project.get("project_id"):
            raise RuntimeError("tool response did not contain the JUCE project")
        print(f"MIDI tool smoke passed: {len(names)} tools, project {project['project_id']}")


if __name__ == "__main__":
    main()
