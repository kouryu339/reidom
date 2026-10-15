use std::sync::{Arc, Mutex};

use tauri::Manager;

mod app_paths;
mod conversation_store;
mod commands;
mod engine_client;
mod runtime_host;
mod state;
mod tool_service;

use engine_client::EngineState;
use state::AppState;
use tool_service::ToolServiceState;

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let app_handle = app.handle().clone();
            app.manage(Mutex::new(AppState::new()));
            let repo_root = app_paths::repo_root()?;
            let documents = app.path().app_data_dir()?.join("projects").join("ai");
            std::fs::create_dir_all(&documents)?;
            std::env::set_var("REIDOM_DOCUMENT_DIR", &documents);
            app.manage(Arc::new(Mutex::new(EngineState::start(&repo_root))));
            let tool_service = Arc::new(Mutex::new(ToolServiceState::start(&repo_root)));
            tool_service::spawn_supervisor(Arc::clone(&tool_service));
            app.manage(tool_service);
            AppState::spawn_runtime_connect(app_handle);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::system::console_environment,
            commands::projects::project_library,
            commands::engine::engine_status,
            commands::engine::engine_snapshot,
            commands::engine::engine_edit_mode,
            commands::engine::engine_device_settings,
            commands::engine::engine_configure_devices,
            commands::engine::engine_apply_command,
            commands::engine::engine_demo,
            commands::engine::engine_new_project,
            commands::engine::engine_import_midi,
            commands::engine::engine_export_midi,
            commands::engine::engine_import_project,
            commands::engine::engine_export_project,
            commands::engine::engine_render_wav,
            commands::engine::engine_write_autosave,
            commands::engine::engine_restore_autosave,
            commands::engine::engine_undo,
            commands::engine::engine_redo,
            commands::engine::engine_command_log,
            commands::system::tool_service_status,
            commands::ai::get_instance_status,
            commands::ai::ai_prepare_conversation,
            commands::ai::ai_send_message,
            commands::ai::ai_pending_messages,
            commands::ai::ai_pause_conversation,
            commands::ai::ai_close_conversation,
            commands::ai::ai_resolve_tool_permission,
            commands::ai::ai_runtime_snapshot,
            commands::history::ai_conversation_history,
            commands::providers::ai_get_provider_definitions,
            commands::providers::ai_configure_providers,
            commands::providers::ai_set_conversation_model,
            commands::system::validate_midi_selection
        ])
        .run(tauri::generate_context!())
        .expect("error while running Reidom Console");
}
