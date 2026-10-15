use std::thread;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};

use crate::runtime_host::{RuntimeConnection, RuntimeHost};

#[derive(Default)]
pub struct AppState {
    current_conversation_id: Option<String>,
    project_conversations: std::collections::HashMap<String, String>,
    current_project_id: Option<String>,
    archive_bindings: std::collections::HashMap<String, String>,
    runtime: Option<RuntimeHost>,
    runtime_mode: String,
    runtime_version: String,
    runtime_error: Option<String>,
    runtime_connecting: bool,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            runtime_mode: "starting".to_string(),
            runtime_version: "AI runtime starting".to_string(),
            ..Self::default()
        }
    }

    pub fn spawn_runtime_connect(app: AppHandle) {
        let should_start = {
            let state = app.state::<std::sync::Mutex<AppState>>();
            let mut state = state.lock().expect("app state poisoned");
            if state.runtime.is_some() || state.runtime_connecting {
                false
            } else {
                state.runtime_connecting = true;
                true
            }
        };
        if !should_start {
            return;
        }
        thread::spawn(move || loop {
            let result = RuntimeHost::connect(app.clone());
            let connected = result.is_ok();
            let status = {
                let state = app.state::<std::sync::Mutex<AppState>>();
                let mut state = state.lock().expect("app state poisoned");
                state.apply_runtime_connect_result(result)
            };
            let _ = app.emit("ai-runtime-status", status);
            if connected {
                return;
            }
            thread::sleep(std::time::Duration::from_secs(2));
        });
    }

    pub fn mark_runtime_disconnected(&mut self, error: String) -> Value {
        self.runtime = None;
        self.current_conversation_id = None;
        self.project_conversations.clear();
        self.archive_bindings.clear();
        self.runtime_connecting = false;
        self.runtime_mode = "reconnecting".to_string();
        self.runtime_version = "AI runtime reconnecting".to_string();
        self.runtime_error = Some(error);
        self.instance_status_value()
    }

    pub fn instance_status_value(&self) -> Value {
        json!({
            "name": "Reidom Console",
            "channel": "desktop",
            "runtime": self.runtime_version(),
            "healthy": self.runtime_connected(),
            "runtime_mode": self.runtime_mode(),
            "diagnostic": self.runtime_error()
        })
    }

    pub fn runtime_connected(&self) -> bool {
        self.runtime.is_some()
    }

    pub fn runtime_mode(&self) -> &str {
        &self.runtime_mode
    }

    pub fn runtime_version(&self) -> &str {
        &self.runtime_version
    }

    pub fn runtime_error(&self) -> Option<&str> {
        self.runtime_error.as_deref()
    }

    pub fn ensure_conversation(&mut self) -> Result<String, String> {
        if let Some(conversation_id) = self.current_conversation_id.clone() {
            return Ok(conversation_id);
        }
        let runtime = self
            .runtime
            .as_ref()
            .ok_or_else(|| "AI runtime is not connected".to_string())?;
        let conversation_id = runtime.spawn_conversation()?;
        self.current_conversation_id = Some(conversation_id.clone());
        Ok(conversation_id)
    }

    pub fn project_conversation(&mut self, project_id: String) -> Result<String, String> {
        if self.current_project_id.as_ref() != Some(&project_id) {
            if let Some(old) = &self.current_conversation_id {
                self.invoke_runtime("conversation.pause", json!({"conversation_id":old}))?;
            }
            self.current_conversation_id = self.project_conversations.get(&project_id).cloned();
            self.current_project_id = Some(project_id.clone());
        }
        let conversation = self.ensure_conversation()?;
        self.project_conversations.insert(project_id, conversation.clone());
        Ok(conversation)
    }

    pub fn normalize_conversation_id(
        &mut self,
        conversation_id: Option<String>,
    ) -> Result<String, String> {
        if let Some(conversation_id) =
            conversation_id.filter(|value| !value.trim().is_empty() && value.starts_with("conv_"))
        {
            if self.current_conversation_id.as_ref() != Some(&conversation_id) {
                return Err("会话已随项目切换，请重新连接当前项目".into());
            }
            return Ok(conversation_id);
        }
        self.ensure_conversation()
    }

    pub fn invoke_runtime(&self, command_type: &str, payload: Value) -> Result<Value, String> {
        self.runtime
            .as_ref()
            .ok_or_else(|| "AI runtime is not connected".to_string())?
            .invoke(command_type, payload)
    }

    pub fn require_project(&self, project_id: &str) -> Result<(), String> {
        if self.current_project_id.as_deref() != Some(project_id) {
            return Err("作品已切换，请重新打开会话历史".into());
        }
        Ok(())
    }

    pub fn archive_id(&self, conversation_id: &str) -> String {
        self.archive_bindings.get(conversation_id).cloned().unwrap_or_else(|| conversation_id.into())
    }

    pub fn replace_conversation(&mut self, snapshot: Option<Value>, archive_id: Option<String>) -> Result<String, String> {
        let project = self.current_project_id.clone().ok_or("请先打开作品")?;
        let old = self.current_conversation_id.clone();
        let id = self.runtime.as_ref().ok_or("AI runtime is not connected")?.spawn_from_checkpoint(snapshot)?;
        if let Some(old) = old {
            if let Err(error) = self.invoke_runtime("conversation.close", json!({"conversation_id":old})) {
                let _ = self.invoke_runtime("conversation.close", json!({"conversation_id":id}));
                return Err(error);
            }
            self.archive_bindings.remove(&old);
        }
        self.archive_bindings.insert(id.clone(), archive_id.unwrap_or_else(|| id.clone()));
        self.current_conversation_id = Some(id.clone());
        self.project_conversations.insert(project, id.clone());
        Ok(id)
    }

    fn apply_runtime_connect_result(&mut self, result: Result<RuntimeConnection, String>) -> Value {
        match result {
            Ok(connection) => {
                self.runtime = Some(connection.host);
                self.runtime_mode = "embedded-ai-runtime".to_string();
                self.runtime_version = format!(
                    "{} ({})",
                    connection.version,
                    connection.library_path.display()
                );
                self.runtime_error = None;
                self.runtime_connecting = false;
            }
            Err(error) => {
                eprintln!("[reidom-tauri] runtime connect failed: {error}");
                self.runtime = None;
                self.runtime_mode = "unavailable".to_string();
                self.runtime_version = "AI runtime unavailable".to_string();
                self.runtime_error = Some(error);
                self.runtime_connecting = true;
            }
        }
        self.instance_status_value()
    }
}
