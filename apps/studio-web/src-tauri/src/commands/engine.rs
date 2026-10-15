use std::fs;
use std::sync::Arc;

use serde_json::{json, Value};
use tauri::{AppHandle, Manager, State};

use super::SharedEngine;

async fn call_engine(state: State<'_, SharedEngine>, request: Value) -> Result<Value, String> {
    let engine = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || {
        engine
            .lock()
            .map_err(|_| "JUCE engine state poisoned".to_string())?
            .call(request)
    })
    .await
    .map_err(|error| format!("join JUCE engine call: {error}"))?
}

#[tauri::command]
pub async fn engine_edit_mode(state: State<'_, SharedEngine>, mode: String) -> Result<Value, String> {
    call_engine(state, json!({"method":"edit.mode", "source":"user", "mode":mode})).await
}

#[tauri::command]
pub async fn engine_status(state: State<'_, SharedEngine>) -> Result<Value, String> {
    let engine = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || {
        Ok(engine
            .lock()
            .map_err(|_| "JUCE engine state poisoned".to_string())?
            .status())
    })
    .await
    .map_err(|error| format!("join JUCE engine status: {error}"))?
}

#[tauri::command]
pub async fn engine_snapshot(state: State<'_, SharedEngine>) -> Result<Value, String> {
    call_engine(state, json!({"method": "snapshot.get"})).await
}

#[tauri::command]
pub async fn engine_device_settings(state: State<'_, SharedEngine>) -> Result<Value, String> {
    call_engine(state, json!({"method": "devices.get"})).await
}

#[tauri::command]
pub async fn engine_configure_devices(
    state: State<'_, SharedEngine>,
    output_device: String,
    sample_rate: f64,
    buffer_size: i64,
    midi_input_ids: Vec<String>,
) -> Result<Value, String> {
    call_engine(
        state,
        json!({
            "method": "devices.configure",
            "output_device": output_device,
            "sample_rate": sample_rate,
            "buffer_size": buffer_size,
            "midi_input_ids": midi_input_ids,
        }),
    )
    .await
}

#[tauri::command]
pub async fn engine_apply_command(
    state: State<'_, SharedEngine>,
    command: Value,
) -> Result<Value, String> {
    call_engine(
        state,
        json!({"method": "command.apply", "command": command}),
    )
    .await
}

#[tauri::command]
pub async fn engine_demo(state: State<'_, SharedEngine>) -> Result<Value, String> {
    call_engine(state, json!({"method": "project.demo"})).await
}

#[tauri::command]
pub async fn engine_new_project(
    state: State<'_, SharedEngine>,
    name: String,
    tempo: f64,
) -> Result<Value, String> {
    call_engine(
        state,
        json!({"method": "project.new", "name": name, "tempo": tempo}),
    )
    .await
}

#[tauri::command]
pub async fn engine_import_midi(
    state: State<'_, SharedEngine>,
    file_name: String,
    data_base64: String,
) -> Result<Value, String> {
    call_engine(
        state,
        json!({
            "method": "project.import_midi",
            "file_name": file_name,
            "data_base64": data_base64,
        }),
    )
    .await
}

#[tauri::command]
pub async fn engine_export_midi(state: State<'_, SharedEngine>) -> Result<Value, String> {
    call_engine(state, json!({"method": "project.export_midi"})).await
}

#[tauri::command]
pub async fn engine_import_project(
    state: State<'_, SharedEngine>,
    project: Value,
) -> Result<Value, String> {
    call_engine(
        state,
        json!({"method": "project.import_json", "project": project, "source": "user"}),
    )
    .await
}

#[tauri::command]
pub async fn engine_export_project(state: State<'_, SharedEngine>) -> Result<Value, String> {
    call_engine(state, json!({"method": "project.export_json"})).await
}

#[tauri::command]
pub async fn engine_render_wav(state: State<'_, SharedEngine>) -> Result<Value, String> {
    call_engine(state, json!({"method": "project.render_wav"})).await
}

fn autosave_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    Ok(app
        .path()
        .app_data_dir()
        .map_err(|error| format!("resolve app data directory: {error}"))?
        .join("projects")
        .join("recovery.reidom"))
}

#[tauri::command]
pub async fn engine_write_autosave(
    app: AppHandle,
    state: State<'_, SharedEngine>,
) -> Result<Value, String> {
    let exported = call_engine(state, json!({"method": "project.export_json"})).await?;
    let path = autosave_path(&app)?;
    let parent = path
        .parent()
        .ok_or_else(|| "invalid autosave path".to_string())?;
    fs::create_dir_all(parent).map_err(|error| format!("create autosave directory: {error}"))?;
    let temporary = path.with_extension("reidom.tmp");
    let bytes = serde_json::to_vec_pretty(&exported)
        .map_err(|error| format!("encode autosave: {error}"))?;
    fs::write(&temporary, bytes).map_err(|error| format!("write autosave: {error}"))?;
    if path.exists() {
        let backup = path.with_extension("reidom.bak");
        let _ = fs::remove_file(&backup);
        fs::rename(&path, &backup).map_err(|error| format!("rotate autosave: {error}"))?;
    }
    fs::rename(&temporary, &path).map_err(|error| format!("commit autosave: {error}"))?;
    Ok(json!({"saved": true, "path": path}))
}

#[tauri::command]
pub async fn engine_restore_autosave(
    app: AppHandle,
    state: State<'_, SharedEngine>,
) -> Result<Value, String> {
    let path = autosave_path(&app)?;
    if !path.is_file() {
        return Ok(Value::Null);
    }
    let text = fs::read_to_string(&path).map_err(|error| format!("read autosave: {error}"))?;
    let saved: Value =
        serde_json::from_str(&text).map_err(|error| format!("parse autosave: {error}"))?;
    let project = saved
        .get("project")
        .cloned()
        .ok_or_else(|| "autosave contains no project".to_string())?;
    call_engine(
        state,
        json!({"method": "project.import_json", "project": project, "source": "restore"}),
    )
    .await
}

#[tauri::command]
pub async fn engine_undo(state: State<'_, SharedEngine>) -> Result<Value, String> {
    call_engine(state, json!({"method": "history.undo"})).await
}

#[tauri::command]
pub async fn engine_redo(state: State<'_, SharedEngine>) -> Result<Value, String> {
    call_engine(state, json!({"method": "history.redo"})).await
}

#[tauri::command]
pub async fn engine_command_log(state: State<'_, SharedEngine>) -> Result<Value, String> {
    call_engine(state, json!({"method": "history.get"})).await
}
