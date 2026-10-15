use crate::{conversation_store::ConversationStore, state::AppState};
use serde_json::{json, Value};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};

pub fn waiting_checkpoint(state: &AppState, id: &str) -> Result<Value, String> {
    let snapshot = state.invoke_runtime(
        "conversation.export_snapshot",
        json!({"conversation_id":id}),
    )?;
    if snapshot["conversation_state"] != "waiting" || snapshot["stable"] != true {
        return Err("AI 正在工作，请先停止并等待完成，再切换会话或修改模型配置".into());
    }
    Ok(snapshot)
}

#[tauri::command]
pub fn ai_conversation_history(
    app: AppHandle,
    state: State<'_, Mutex<AppState>>,
    project_id: String,
    action: String,
    conversation_id: Option<String>,
    archive_id: Option<String>,
    title: Option<String>,
) -> Result<Value, String> {
    let mut state = state.lock().map_err(|_| "会话状态暂不可用")?;
    state.require_project(&project_id)?;
    let root = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("conversations");
    let store = ConversationStore::new(&root, &project_id)?;
    let current = state.normalize_conversation_id(conversation_id)?;
    let current_archive = state.archive_id(&current);
    if action == "list" {
        let mut items = store.list()?;
        for item in &mut items {
            if item["archiveId"] == current_archive {
                item["runtimeConversationId"] = json!(current);
                item["status"] = json!("running");
                item["instanceState"] = json!("current");
            }
        }
        return Ok(json!({"items":items}));
    }
    if !["save", "create", "restore"].contains(&action.as_str()) {
        return Err("不支持的会话操作".into());
    }
    let snapshot = waiting_checkpoint(&state, &current)?;
    if action == "save" {
        if archive_id.as_ref().is_some_and(|id| id != &current_archive) {
            return Err("会话绑定已变化，请重新保存".into());
        }
        let mut metadata = store.save(&current_archive, &snapshot, title.as_deref())?;
        metadata["runtimeConversationId"] = json!(current);
        metadata["instanceState"] = json!("current");
        metadata["status"] = json!("running");
        return Ok(metadata);
    }
    // Validate the target before saving or replacing the current conversation.
    let target = if action == "restore" {
        Some(store.restore(archive_id.as_deref().ok_or("请选择会话历史")?)?)
    } else {
        None
    };
    if snapshot["ledger"]
        .as_array()
        .is_some_and(|records| !records.is_empty())
        || store.contains(&current_archive)?
    {
        store.save(&current_archive, &snapshot, None)?;
    }
    let id = state.replace_conversation(target, archive_id)?;
    Ok(json!({"archiveId":state.archive_id(&id),"runtimeConversationId":id}))
}
