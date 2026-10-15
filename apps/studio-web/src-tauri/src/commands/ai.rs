use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::State;

use super::SharedToolService;
use crate::state::AppState;

#[derive(Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub struct ConversationId {
    conversation_id: String,
}

#[derive(Debug, Serialize)]
pub struct CommandResult {
    accepted: bool,
    command_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConversationArgs {
    #[serde(alias = "conversation_id")]
    conversation_id: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SendMessageArgs {
    #[serde(alias = "conversation_id")]
    conversation_id: Option<String>,
    content: String,
    #[serde(alias = "client_message_id")]
    client_message_id: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolPermissionArgs {
    #[serde(alias = "conversation_id")]
    conversation_id: Option<String>,
    #[serde(alias = "tool_call_id")]
    tool_call_id: String,
    decision: String,
}

#[tauri::command]
pub fn get_instance_status(
    state: State<'_, Mutex<AppState>>,
    tool_service: State<'_, SharedToolService>,
) -> Value {
    let mut status = state
        .lock()
        .expect("app state poisoned")
        .instance_status_value();
    let tool_status = tool_service
        .lock()
        .map(|mut service| service.status())
        .unwrap_or_else(|_| json!({"healthy": false, "diagnostic": "MIDI tool state poisoned"}));
    let runtime_healthy = status
        .get("healthy")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let tools_healthy = tool_status
        .get("healthy")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    status["runtime_healthy"] = json!(runtime_healthy);
    status["tool_service"] = tool_status;
    status["healthy"] = json!(runtime_healthy && tools_healthy);
    status
}

#[tauri::command]
pub fn ai_prepare_conversation(
    state: State<'_, Mutex<AppState>>,
    project_id: Option<String>,
) -> Result<ConversationId, String> {
    let mut state = state.lock().expect("app state poisoned");
    let conversation_id = match project_id {
        Some(id) => state.project_conversation(id)?,
        None => state.ensure_conversation()?,
    };
    Ok(ConversationId { conversation_id })
}

#[tauri::command]
pub fn ai_send_message(state: State<'_, Mutex<AppState>>, args: SendMessageArgs) -> CommandResult {
    let mut state = state.lock().expect("app state poisoned");
    let conversation_id = match state.normalize_conversation_id(args.conversation_id) {
        Ok(conversation_id) => conversation_id,
        Err(error) => {
            return CommandResult {
                accepted: false,
                command_id: error,
            };
        }
    };
    match state.invoke_runtime(
        "conversation.send_message",
        json!({
            "conversation_id": conversation_id,
            "content": args.content,
            "client_message_id": args.client_message_id
        }),
    ) {
        Ok(result) => CommandResult {
            accepted: true,
            command_id: result
                .get("command_id")
                .and_then(Value::as_str)
                .unwrap_or("send-message")
                .to_string(),
        },
        Err(error) => CommandResult {
            accepted: false,
            command_id: error,
        },
    }
}

#[tauri::command]
pub fn ai_pending_messages() -> Vec<Value> {
    Vec::new()
}

#[tauri::command]
pub fn ai_pause_conversation(
    state: State<'_, Mutex<AppState>>,
    args: ConversationArgs,
) -> CommandResult {
    let mut state = state.lock().expect("app state poisoned");
    let conversation_id = match state.normalize_conversation_id(args.conversation_id) {
        Ok(value) => value,
        Err(error) => {
            return CommandResult {
                accepted: false,
                command_id: error,
            }
        }
    };
    runtime_command_result(
        &mut state,
        "conversation.pause",
        json!({ "conversation_id": conversation_id }),
        "pause",
    )
}

#[tauri::command]
pub fn ai_close_conversation(
    state: State<'_, Mutex<AppState>>,
    args: ConversationArgs,
) -> CommandResult {
    let mut state = state.lock().expect("app state poisoned");
    let conversation_id = match state.normalize_conversation_id(args.conversation_id) {
        Ok(value) => value,
        Err(error) => {
            return CommandResult {
                accepted: false,
                command_id: error,
            }
        }
    };
    runtime_command_result(
        &mut state,
        "conversation.close",
        json!({ "conversation_id": conversation_id }),
        "close",
    )
}

#[tauri::command]
pub fn ai_resolve_tool_permission(
    state: State<'_, Mutex<AppState>>,
    args: ToolPermissionArgs,
) -> CommandResult {
    let mut state = state.lock().expect("app state poisoned");
    let conversation_id = match state.normalize_conversation_id(args.conversation_id) {
        Ok(value) => value,
        Err(error) => {
            return CommandResult {
                accepted: false,
                command_id: error,
            }
        }
    };
    runtime_command_result(
        &mut state,
        "conversation.resolve_tool_permission",
        json!({
            "conversation_id": conversation_id,
            "tool_call_id": args.tool_call_id,
            "decision": args.decision
        }),
        "resolve-tool-permission",
    )
}

fn runtime_command_result(
    state: &mut AppState,
    command: &str,
    args: Value,
    fallback_id: &str,
) -> CommandResult {
    match state.invoke_runtime(command, args) {
        Ok(result) => CommandResult {
            accepted: true,
            command_id: result
                .get("command_id")
                .and_then(Value::as_str)
                .unwrap_or(fallback_id)
                .to_string(),
        },
        Err(error) => CommandResult {
            accepted: false,
            command_id: error,
        },
    }
}

#[tauri::command]
pub fn ai_runtime_snapshot(
    state: State<'_, Mutex<AppState>>,
    args: Option<ConversationArgs>,
) -> Result<Value, String> {
    let mut state = state.lock().expect("app state poisoned");
    let conversation_id =
        state.normalize_conversation_id(args.and_then(|args| args.conversation_id))?;
    state.invoke_runtime(
        "conversation.export_snapshot",
        json!({ "conversation_id": conversation_id }),
    )
}
