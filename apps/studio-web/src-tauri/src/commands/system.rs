use std::sync::Arc;

use serde::Serialize;
use serde_json::Value;
use tauri::State;

use super::SharedToolService;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConsoleEnvironment {
    app_name: &'static str,
    runtime_owner: &'static str,
    project_owner: &'static str,
}

#[tauri::command]
pub fn console_environment() -> ConsoleEnvironment {
    ConsoleEnvironment {
        app_name: "Reidom Studio",
        runtime_owner: "tauri",
        project_owner: "juce-engine",
    }
}

#[tauri::command]
pub async fn tool_service_status(state: State<'_, SharedToolService>) -> Result<Value, String> {
    let service = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || {
        Ok(service
            .lock()
            .map_err(|_| "MIDI tool service state poisoned".to_string())?
            .status())
    })
    .await
    .map_err(|error| format!("join MIDI tool service status: {error}"))?
}

#[tauri::command]
pub fn validate_midi_selection(selection: serde_json::Value) -> Result<serde_json::Value, String> {
    let schema = selection
        .get("schema")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "selection.schema is required".to_string())?;
    if schema != "reidom-midi-selection/v1" {
        return Err("expected reidom-midi-selection/v1".to_string());
    }
    if selection
        .get("tracks")
        .and_then(serde_json::Value::as_array)
        .is_none()
    {
        return Err("selection.tracks must be an array".to_string());
    }
    Ok(selection)
}
