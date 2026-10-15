use std::sync::{Arc, Mutex};

use crate::engine_client::EngineState;
use crate::tool_service::ToolServiceState;

pub mod ai;
pub mod engine;
pub mod system;
pub mod projects;
pub mod history;
pub mod providers;

pub type SharedEngine = Arc<Mutex<EngineState>>;
pub type SharedToolService = Arc<Mutex<ToolServiceState>>;
