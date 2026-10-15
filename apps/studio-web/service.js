export class ReidomService {
  constructor() {
    this.isNative = "__TAURI_INTERNALS__" in window;
    this.invoke = null;
  }

  async hydrate() {
    if (!this.isNative) return;
    const core = await import("@tauri-apps/api/core");
    this.invoke = core.invoke;
  }

  async context() {
    const snapshotBundle = await this.#call("engine_snapshot");
    return { schema: "reidom-console-context/v2", snapshot_bundle: snapshotBundle };
  }

  async setEditMode(mode) {
    return this.#call("engine_edit_mode", { mode });
  }

  async health() {
    return this.#call("engine_status");
  }

  async deviceSettings() {
    return this.#call("engine_device_settings");
  }

  async configureDevices(settings) {
    return this.#call("engine_configure_devices", {
      outputDevice: settings.outputDevice || "",
      sampleRate: Number(settings.sampleRate || 0),
      bufferSize: Number(settings.bufferSize || 0),
      midiInputIds: settings.midiInputIds || [],
    });
  }

  async publishMidiSelection(selection) {
    const context = await this.context();
    const project = context.snapshot_bundle.ui_snapshot.project;
    return this.executeCommand(project.project_id, {
      command_id: `cmd-${Date.now()}`,
      base_revision: project.revision,
      source: "user",
      type: "selection.set",
      payload: {
        note_ids: selection.selected_note_ids || [],
        clip_ids: selection.selected_clip_ids || [],
      },
    });
  }

  async importMidiFile(file) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const snapshot = await this.#call("engine_import_midi", {
      fileName: file.name,
      dataBase64: bytesToBase64(bytes),
    });
    return projectResponse(snapshot);
  }

  async createDemoProject() {
    return projectResponse(await this.#call("engine_demo"));
  }

  async createProject(name = "未命名作品", tempo = 120) {
    return projectResponse(await this.#call("engine_new_project", { name, tempo }));
  }

  async importProjectFile(file) {
    const envelope = JSON.parse(await file.text());
    const project = envelope.project || envelope;
    return projectResponse(await this.#call("engine_import_project", { project }));
  }

  async exportProject() {
    return this.#call("engine_export_project");
  }

  async renderWav() {
    return this.#call("engine_render_wav");
  }

  async writeAutosave() {
    await this.#call("project_library", { action: "save", id: null });
    return this.#call("engine_write_autosave");
  }

  async listProjects() {
    return this.#call("project_library", { action: "list", id: null });
  }

  async openLibraryProject(id) {
    return projectResponse(await this.#call("project_library", { action: "open", id }));
  }

  async restoreAutosave() {
    const snapshot = await this.#call("engine_restore_autosave");
    return snapshot ? projectResponse(snapshot) : null;
  }

  async executeCommand(_projectId, command) {
    const commandId = command.command_id || `cmd-${Date.now()}`;
    const result = await this.#call("engine_apply_command", {
      command: {
        ...command,
        schema: "reidom-command/v2",
        command_id: commandId,
        idempotency_key: command.idempotency_key || commandId,
        project_id: command.project_id || _projectId,
        reason: command.reason || "",
      },
    });
    return projectResponse(result.snapshot);
  }

  async undo(_projectId) {
    return projectResponse(await this.#call("engine_undo"));
  }

  async redo(_projectId) {
    return projectResponse(await this.#call("engine_redo"));
  }

  async exportMidi(_projectId) {
    return this.#call("engine_export_midi");
  }

  async commandLog(_projectId, _includeSnapshots = false) {
    return this.#call("engine_command_log");
  }

  async sendConsoleMessage() {
    throw new Error("AI Runtime is unavailable");
  }

  async #call(command, payload = {}) {
    if (!this.invoke) throw new Error("JUCE engine is available only in the Reidom desktop app");
    return this.invoke(command, payload);
  }
}

function projectResponse(snapshot) {
  const ui = snapshot?.ui_snapshot;
  if (!ui?.project) throw new Error("JUCE engine returned no UI snapshot");
  return { project: ui.project, selection: ui.selection, snapshot_bundle: snapshot };
}

export class ReidomRuntimeBridge {
  constructor() {
    this.isNative = "__TAURI_INTERNALS__" in window;
    this.invoke = null;
    this.listen = null;
    this.unlisteners = [];
    this.status = {
      healthy: false,
      runtime_mode: this.isNative ? "starting" : "browser",
      runtime: this.isNative ? "AI starting" : "browser preview",
      diagnostic: null,
    };
    this.conversationId = null;
  }

  async hydrate(handlers = {}) {
    if (!this.isNative) return this.status;
    const core = await import("@tauri-apps/api/core");
    const event = await import("@tauri-apps/api/event");
    this.invoke = core.invoke;
    this.listen = event.listen;
    await this.#listen("ai-runtime-status", (payload) => {
      this.status = normalizeStatus(payload);
      handlers.onStatus?.(this.status);
    });
    await this.#listen("ai-runtime-diagnostic", (payload) => {
      handlers.onDiagnostic?.(payload);
    });
    if (handlers.onFrontendEvent) {
      await this.#listen("ai-frontend-event", handlers.onFrontendEvent);
    }
    return this.refreshStatus();
  }

  async refreshStatus() {
    if (!this.invoke) return this.status;
    this.status = normalizeStatus(await this.invoke("get_instance_status"));
    return this.status;
  }

  async prepareConversation() {
    const result = await this.#call("ai_prepare_conversation");
    this.conversationId = result.conversation_id;
    return this.conversationId;
  }

  async sendMessage(content) {
    const conversationId = await this.prepareConversation();
    return this.#call("ai_send_message", {
      args: {
        conversationId,
        content,
      },
    });
  }

  async runtimeSnapshot() {
    const conversationId = await this.prepareConversation();
    return this.#call("ai_runtime_snapshot", {
      args: { conversationId },
    });
  }

  async dispose() {
    const unlisteners = this.unlisteners.splice(0);
    await Promise.allSettled(unlisteners.map((unlisten) => unlisten()));
  }

  async #listen(eventName, handler) {
    const unlisten = await this.listen(eventName, (event) => handler(event.payload));
    this.unlisteners.push(unlisten);
  }

  async #call(command, payload) {
    if (!this.invoke) {
      throw new Error("Tauri runtime bridge is not available");
    }
    return this.invoke(command, payload);
  }
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
}

function normalizeStatus(value) {
  return {
    healthy: Boolean(value?.healthy),
    runtime_mode: value?.runtime_mode || value?.runtimeMode || "unknown",
    runtime: value?.runtime || "AI unavailable",
    diagnostic: value?.diagnostic || null,
  };
}
