from __future__ import annotations

import base64
import binascii
from contextlib import asynccontextmanager
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .ardour_frontend_state import build_ardour_frontend_state
from .bridge_store import BridgeStore
from .daw_registry import DawAdapterRegistry
from .project_store import MidiParseError, ProjectStore, project_to_selection
from .runtime_adapter import RuntimeAdapter
from .settings import Settings
from .snapshot_bundle import build_snapshot_bundle


class SelectionEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_name: Literal["reidom-midi-selection/v1"] = Field(alias="schema")
    selection_id: str
    project_id: str
    revision: int = Field(ge=0)
    tracks: list[dict[str, Any]]


class MessageInput(BaseModel):
    content: str = Field(min_length=1)
    selection: dict[str, Any] | None = None


class ImportMidiInput(BaseModel):
    file_name: str = Field(min_length=1)
    data_base64: str = Field(min_length=1)


class CommandInput(BaseModel):
    command_id: str | None = None
    base_revision: int = Field(ge=0)
    source: Literal["user", "ai", "daw-adapter"] = "user"
    type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    preview: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = BridgeStore(settings.bridge_dir)
    project_store = ProjectStore(settings.bridge_dir)
    daw_registry = DawAdapterRegistry(settings.daw_manifest_path)
    runtime: RuntimeAdapter | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal runtime
        if settings.runtime_library is not None:
            runtime = RuntimeAdapter(
                settings.runtime_library,
                settings.repo_root / "data" / "runtime",
            )
            runtime.start(
                settings.resources_path,
                settings.llm_path,
                settings.cluster_path,
            )
        app.state.runtime = runtime
        yield
        if runtime is not None:
            runtime.close()

    app = FastAPI(title="Reidom Runtime Host", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    studio_dir = settings.repo_root / "apps" / "studio-web"
    if studio_dir.exists():
        app.mount("/studio", StaticFiles(directory=studio_dir, html=True), name="studio")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "runtime_enabled": settings.runtime_library is not None,
            "bridge_dir": str(settings.bridge_dir),
        }

    @app.get("/v1/daws")
    def daws() -> dict[str, Any]:
        return {"adapters": daw_registry.adapters()}

    @app.get("/v1/daws/{daw_id}")
    def daw(daw_id: str) -> dict[str, Any]:
        adapter = daw_registry.adapter(daw_id)
        if adapter is None:
            raise HTTPException(status_code=404, detail=f"unknown DAW adapter: {daw_id}")
        return adapter

    @app.put("/v1/daws/{daw_id}/selection")
    def publish_daw_selection(daw_id: str, selection: SelectionEnvelope) -> dict[str, Any]:
        if daw_registry.adapter(daw_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown DAW adapter: {daw_id}")
        value = selection.model_dump(mode="json", by_alias=True)
        store.publish_selection(value, adapter_id=daw_id)
        return {"accepted": True, "daw_id": daw_id, "selection_id": selection.selection_id}

    @app.get("/v1/daws/{daw_id}/selection")
    def current_daw_selection(daw_id: str) -> dict[str, Any]:
        if daw_registry.adapter(daw_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown DAW adapter: {daw_id}")
        selection = store.current_selection(adapter_id=daw_id)
        if selection is None:
            raise HTTPException(status_code=404, detail=f"no active selection for {daw_id}")
        return selection

    @app.get("/v1/daws/{daw_id}/commands")
    def daw_commands(daw_id: str) -> list[dict[str, Any]]:
        if daw_registry.adapter(daw_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown DAW adapter: {daw_id}")
        return store.commands(adapter_id=daw_id)

    def snapshot_for_project(active_project: dict[str, Any] | None) -> dict[str, Any]:
        project_selection = (
            active_project.get("selection") if isinstance(active_project, dict) else None
        )
        snapshot_selection = (
            project_selection if isinstance(project_selection, dict) else store.current_selection()
        )
        adapter_id = None
        if isinstance(snapshot_selection, dict):
            source = snapshot_selection.get("source")
            if isinstance(source, dict):
                adapter_id = source.get("daw_id") or source.get("adapter_id")
        active_adapter = daw_registry.adapter(str(adapter_id)) if adapter_id else None
        return build_snapshot_bundle(active_project, snapshot_selection, active_adapter)

    @app.get("/v1/console/context")
    def console_context() -> dict[str, Any]:
        """Single frontend context endpoint for DAW state and future AI state."""

        active_project = project_store.active_project()
        active_selection = store.current_selection()
        snapshot_bundle = snapshot_for_project(active_project)
        return {
            "schema": "reidom-console-context/v1",
            "runtime_enabled": settings.runtime_library is not None,
            "bridge_dir": str(settings.bridge_dir),
            "adapters": daw_registry.adapters(),
            "active_project": active_project,
            "active_selection": active_selection,
            "snapshot_bundle": snapshot_bundle,
            "ai_snapshot": snapshot_bundle["ai_snapshot"]["fields"],
        }

    @app.get("/v2/snapshot")
    def current_snapshot() -> dict[str, Any]:
        active_project = project_store.active_project()
        return snapshot_for_project(active_project)

    @app.post("/v1/projects/import-midi")
    def import_midi(input_value: ImportMidiInput) -> dict[str, Any]:
        try:
            data = base64.b64decode(input_value.data_base64, validate=True)
            project = project_store.import_midi(input_value.file_name, data)
        except (binascii.Error, MidiParseError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        selection = project_to_selection(project)
        store.publish_selection(selection, adapter_id="midi-file")
        return {"project": project, "selection": selection}

    @app.post("/v1/projects/demo")
    def demo_project() -> dict[str, Any]:
        project = project_store.demo_project()
        selection = project_to_selection(project)
        store.publish_selection(selection, adapter_id="midi-file")
        return {"project": project, "selection": selection}

    @app.get("/v1/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        project = project_store.project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"unknown project: {project_id}")
        return project

    @app.post("/v1/projects/{project_id}/commands")
    def execute_command(project_id: str, command: CommandInput) -> dict[str, Any]:
        command_value = command.model_dump(mode="json")
        command_value["schema"] = "reidom-command/v1"
        command_value["command_id"] = command.command_id or f"cmd-{project_id}-{command.type}"
        try:
            project = project_store.apply_command(project_id, command_value)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        selection = project_to_selection(project)
        store.publish_selection(selection, adapter_id="midi-file")
        return {"project": project, "selection": project.get("selection") or selection}

    @app.post("/v1/projects/{project_id}/undo")
    def undo_project(project_id: str) -> dict[str, Any]:
        try:
            project = project_store.undo(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        selection = project.get("selection") or project_to_selection(project)
        store.publish_selection(selection, adapter_id="midi-file")
        return {"project": project, "selection": selection}

    @app.post("/v1/projects/{project_id}/redo")
    def redo_project(project_id: str) -> dict[str, Any]:
        try:
            project = project_store.redo(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        selection = project.get("selection") or project_to_selection(project)
        store.publish_selection(selection, adapter_id="midi-file")
        return {"project": project, "selection": selection}

    @app.get("/v1/projects/{project_id}/command-log")
    def project_command_log(
        project_id: str,
        include_snapshots: bool = False,
    ) -> dict[str, Any]:
        try:
            return project_store.command_log(
                project_id,
                include_snapshots=include_snapshots,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/projects/{project_id}/export-midi")
    def export_midi(project_id: str) -> dict[str, Any]:
        try:
            file_name, data = project_store.export_midi(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "schema": "reidom-midi-export/v1",
            "file_name": file_name,
            "data_base64": base64.b64encode(data).decode("ascii"),
        }

    @app.post("/v1/console/messages")
    def console_message(message: MessageInput) -> dict[str, Any]:
        """Unified placeholder endpoint for the future ai-framework conversation.

        The frontend should call this same host service for both DAW state and AI
        messaging. When the Runtime ABI is enabled, this endpoint can delegate to
        RuntimeAdapter instead of changing the frontend contract.
        """

        return {
            "schema": "reidom-console-message/v1",
            "mode": "placeholder",
            "assistant": {
                "role": "assistant",
                "content": (
                    "AI arranger service is reserved here. Next step: route this "
                    "message into ai-framework and let tools run reversible "
                    "MIDI commands from the current project context."
                ),
            },
        }

    @app.put("/v1/ardour/selection")
    def publish_selection(selection: SelectionEnvelope) -> dict[str, Any]:
        value = selection.model_dump(mode="json", by_alias=True)
        store.publish_selection(value, adapter_id="ardour")
        return {"accepted": True, "selection_id": selection.selection_id}

    @app.get("/v1/ardour/selection")
    def current_selection() -> dict[str, Any]:
        selection = store.current_selection(adapter_id="ardour")
        if selection is None:
            raise HTTPException(status_code=404, detail="no active MIDI selection")
        return selection

    @app.get("/v1/ardour/commands")
    def commands() -> list[dict[str, Any]]:
        return store.commands(adapter_id="ardour")

    @app.get("/v1/ardour/frontend-state", deprecated=True)
    def ardour_frontend_state() -> dict[str, Any]:
        active_project = project_store.active_project()
        active_selection = store.current_selection(adapter_id="ardour")
        if active_selection is None:
            active_selection = store.current_selection()
        adapter_id = None
        if isinstance(active_selection, dict):
            source = active_selection.get("source")
            if isinstance(source, dict):
                adapter_id = source.get("daw_id") or source.get("adapter_id")
        active_adapter = daw_registry.adapter(str(adapter_id)) if adapter_id else None
        return build_ardour_frontend_state(active_project, active_selection, active_adapter)

    @app.post("/v1/conversations")
    def spawn_conversation() -> dict[str, Any]:
        active = app.state.runtime
        if active is None:
            raise HTTPException(status_code=503, detail="agent runtime is disabled")
        return active.spawn_conversation()

    @app.post("/v1/conversations/{conversation_id}/messages")
    def send_message(conversation_id: str, message: MessageInput) -> dict[str, Any]:
        active = app.state.runtime
        if active is None:
            raise HTTPException(status_code=503, detail="agent runtime is disabled")
        return active.send_message(conversation_id, message.content)

    return app


app = create_app()


def run() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "reidom_runtime_host.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
