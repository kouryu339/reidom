use super::history::waiting_checkpoint;
use crate::{
    app_paths::ReidomPaths, conversation_store::write_atomic,
    runtime_host::read_llm_registration_json, state::AppState,
};
use serde_json::{json, Value};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};

#[tauri::command]
pub fn ai_get_provider_definitions(state: State<'_, Mutex<AppState>>) -> Result<Value, String> {
    state
        .lock()
        .map_err(|_| "模型设置暂不可用")?
        .invoke_runtime("runtime.get_provider_definitions", json!({}))
}

// UI definitions never contain keys. An unchanged provider's blank key means keep it.
fn preserve_keys(registration: &mut Value, previous: &Value) -> Result<(), String> {
    if registration["schema"] != "agent-runtime-llm-registration/v1" {
        return Err("不支持的模型配置格式".into());
    }
    let providers = registration["providers"]
        .as_array_mut()
        .ok_or("缺少服务商列表")?;
    if providers.len() > 64 {
        return Err("服务商数量过多".into());
    }
    for provider in providers {
        let old = previous["providers"]
            .as_array()
            .and_then(|p| p.iter().find(|old| old["id"] == provider["id"]));
        if provider["api_key"].as_str().unwrap_or("").trim().is_empty() {
            if let Some(old) = old {
                if provider["base_url"] != old["base_url"] {
                    return Err("服务商地址已修改，请重新填写 API Key".into());
                }
                provider["api_key"] = old["api_key"].clone();
            }
        }
    }
    Ok(())
}

#[tauri::command]
pub fn ai_configure_providers(
    app: AppHandle,
    state: State<'_, Mutex<AppState>>,
    input: String,
) -> Result<Value, String> {
    if input.len() > 1024 * 1024 {
        return Err("模型配置内容过大".into());
    }
    let mut registration: Value =
        serde_json::from_str(&input).map_err(|_| "模型配置必须是有效 JSON")?;
    let mut state = state.lock().map_err(|_| "模型设置暂不可用")?;
    let current = state.ensure_conversation()?;
    waiting_checkpoint(&state, &current)?;
    let paths = ReidomPaths::resolve(&app)?;
    let previous = paths
        .llm_providers_path
        .as_deref()
        .map(read_llm_registration_json)
        .transpose()?
        .unwrap_or_else(|| json!({"providers":[]}));
    preserve_keys(&mut registration, &previous)?;
    state
        .invoke_runtime(
            "runtime.configure_providers",
            json!({"registration":registration}),
        )
        .map_err(|_| "Runtime 未接受配置，请检查服务商地址和模型参数")?;
    let target = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("config")
        .join("llm-providers.json");
    if write_atomic(&target, &registration).is_err() {
        let rolled_back = state
            .invoke_runtime(
                "runtime.configure_providers",
                json!({"registration":previous}),
            )
            .is_ok();
        return Err(if rolled_back {
            "保存模型配置失败，已恢复原配置"
        } else {
            "保存失败，内存配置已改变；请重启并重试"
        }
        .into());
    }
    Ok(json!({"accepted":true}))
}

#[tauri::command]
pub fn ai_set_conversation_model(
    state: State<'_, Mutex<AppState>>,
    conversation_id: String,
    model_uid: u32,
) -> Result<Value, String> {
    let mut state = state.lock().map_err(|_| "模型设置暂不可用")?;
    let id = state.normalize_conversation_id(Some(conversation_id))?;
    waiting_checkpoint(&state, &id)?;
    let admission = state.invoke_runtime(
        "conversation.set_model",
        json!({"conversation_id":id,"model_uid":model_uid}),
    )?;
    Ok(
        json!({"accepted":admission["decision"] == "accepted", "commandId":admission["command_id"],"rejectReason":admission["reason"]}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn keeps_keys_but_never_forwards_them_to_a_changed_endpoint() {
        let previous = json!({"providers":[{"id":1,"base_url":"https://original.invalid/v1","api_key":"test-only"}]});
        let mut next = json!({"schema":"agent-runtime-llm-registration/v1","providers":[{"id":1,"base_url":"https://original.invalid/v1","api_key":""}]});
        preserve_keys(&mut next, &previous).unwrap();
        assert_eq!(next["providers"][0]["api_key"], "test-only");
        next["providers"][0]["base_url"] = json!("https://changed.invalid/v1");
        next["providers"][0]["api_key"] = json!("");
        assert!(preserve_keys(&mut next, &previous).is_err());
    }
}
