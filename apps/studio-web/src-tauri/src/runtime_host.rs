use std::env;
use std::ffi::{c_char, c_int, c_uint, CStr, CString};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use libloading::Library;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};

use crate::state::AppState;

use crate::app_paths::{path_string, read_json, ReidomPaths};

const ABI_VERSION: u32 = 1;
const ORBIT_RUNTIME_VERSION: &str = "0.5.0";
const OK: c_int = 0;
const ERR_BAD_STATE: c_int = 3;
const ERR_TIMEOUT: c_int = 4;

type AgentRuntimeHandle = u64;
type AbiVersionFn = unsafe extern "C" fn() -> u32;
type StaticStringFn = unsafe extern "C" fn() -> *const c_char;
type CreateFn = unsafe extern "C" fn(*const c_char, *mut AgentRuntimeHandle) -> c_int;
type StartFn = unsafe extern "C" fn(AgentRuntimeHandle) -> c_int;
type InvokeFn = unsafe extern "C" fn(AgentRuntimeHandle, *const c_char, *mut *mut c_char) -> c_int;
type NextEventFn = unsafe extern "C" fn(AgentRuntimeHandle, c_uint, *mut *mut c_char) -> c_int;
type ShutdownFn = unsafe extern "C" fn(AgentRuntimeHandle, c_uint) -> c_int;
type DestroyFn = unsafe extern "C" fn(AgentRuntimeHandle) -> c_int;
type FreeStringFn = unsafe extern "C" fn(*mut c_char);

#[derive(Clone)]
pub struct RuntimeHost {
    core: Arc<Mutex<RuntimeCore>>,
}

pub struct RuntimeConnection {
    pub host: RuntimeHost,
    pub version: String,
    pub library_path: PathBuf,
}

struct RuntimeCore {
    _library: Library,
    handle: AgentRuntimeHandle,
    version: String,
    create: CreateFn,
    start: StartFn,
    invoke_fn: InvokeFn,
    next_event: NextEventFn,
    shutdown: ShutdownFn,
    destroy: DestroyFn,
    last_error: StaticStringFn,
    free_string: FreeStringFn,
    closed: bool,
}

impl RuntimeHost {
    pub fn connect(app: AppHandle) -> Result<RuntimeConnection, String> {
        let paths = RuntimePaths::discover(&app)?;
        let library_path = paths.library_path.clone();
        let mut core = RuntimeCore::load(&library_path)?;
        core.create_runtime(&paths.create_options)?;

        let resources = read_json(&paths.resources_path)?;
        core.invoke(
            "runtime.register_resources",
            json!({ "registration": resources }),
        )?;

        let llm = match paths.llm_providers_path.as_deref() {
            Some(path) => read_llm_registration_json(path)?,
            None => empty_llm_registration(),
        };
        core.invoke("runtime.register_llm", json!({ "registration": llm }))?;

        let cluster = read_json(&paths.agent_cluster_path)?;
        core.invoke(
            "runtime.register_agent_cluster",
            json!({ "registration": cluster }),
        )?;
        core.start()?;

        let version = core.version.clone();
        let host = RuntimeHost {
            core: Arc::new(Mutex::new(core)),
        };
        host.spawn_event_pump(app);
        Ok(RuntimeConnection {
            host,
            version,
            library_path,
        })
    }

    pub fn invoke(&self, command_type: &str, payload: Value) -> Result<Value, String> {
        let started = Instant::now();
        let mut core = self
            .core
            .lock()
            .map_err(|_| "runtime lock poisoned".to_string())?;
        let result = core.invoke(command_type, payload);
        let elapsed = started.elapsed();
        if elapsed >= Duration::from_millis(250) {
            eprintln!(
                "[reidom-tauri] slow runtime invoke: command={command_type} elapsed_ms={}",
                elapsed.as_millis()
            );
        }
        result
    }

    pub fn spawn_conversation(&self) -> Result<String, String> {
        self.spawn_from_checkpoint(None)
    }

    pub fn spawn_from_checkpoint(&self, snapshot: Option<Value>) -> Result<String, String> {
        let spawn = json!({
            "schema": "agent-runtime-conversation-spawn/v1",
            "cluster_id": "reidom-music",
            "tool_host_context": reidom_tool_host_context()
        });
        let (command, payload) = match snapshot {
            Some(snapshot) => ("conversation.spawn_from_snapshot", json!({"spawn":spawn,"snapshot":snapshot})),
            None => ("conversation.spawn", spawn),
        };
        let result = self.invoke(
            command, payload,
        )?;
        result
            .get("conversation_id")
            .or_else(|| result.get("conversationId"))
            .and_then(Value::as_str)
            .map(str::to_string)
            .ok_or_else(|| format!("conversation.spawn did not return conversation_id: {result}"))
    }

    fn spawn_event_pump(&self, app: AppHandle) -> JoinHandle<()> {
        let reader = self.core.lock().ok().map(|core| core.event_reader());
        thread::spawn(move || loop {
            let Some(reader) = reader else {
                return;
            };
            match reader.next_event(250) {
                Ok(Some(event)) => {
                    let _ = app.emit("ai-frontend-event", event);
                }
                Ok(None) => {}
                Err(error) if error.contains("BAD_STATE") || error.contains("bad state") => {
                    let status = {
                        let state = app.state::<std::sync::Mutex<AppState>>();
                        let mut state = state.lock().expect("app state poisoned");
                        state.mark_runtime_disconnected(error)
                    };
                    let _ = app.emit("ai-runtime-status", status);
                    AppState::spawn_runtime_connect(app.clone());
                    return;
                }
                Err(error) => {
                    let _ = app.emit(
                        "ai-runtime-diagnostic",
                        json!({ "level": "error", "message": error }),
                    );
                }
            }
        })
    }
}

fn reidom_tool_host_context() -> Value {
    json!({
        "reidom": {
            "engine_endpoint": env::var("REIDOM_ENGINE_ENDPOINT")
                .unwrap_or_else(|_| "127.0.0.1:47120".to_string())
        }
    })
}

#[derive(Clone, Copy)]
struct RuntimeEventReader {
    handle: AgentRuntimeHandle,
    next_event: NextEventFn,
    last_error: StaticStringFn,
    free_string: FreeStringFn,
}

impl RuntimeEventReader {
    fn next_event(&self, timeout_ms: u32) -> Result<Option<Value>, String> {
        let mut output: *mut c_char = std::ptr::null_mut();
        let code = unsafe { (self.next_event)(self.handle, timeout_ms, &mut output) };
        if code == ERR_TIMEOUT {
            return Ok(None);
        }
        if code != OK {
            let code_name = if code == ERR_BAD_STATE {
                "BAD_STATE"
            } else {
                "RUNTIME"
            };
            let detail = unsafe { borrowed_string((self.last_error)()) };
            return Err(format!(
                "{code_name} runtime event read failed ({code}): {detail}"
            ));
        }
        if output.is_null() {
            return Ok(None);
        }
        let text = unsafe { borrowed_string(output) };
        unsafe { (self.free_string)(output) };
        Ok(Some(
            serde_json::from_str(&text).unwrap_or_else(|_| json!({ "raw": text })),
        ))
    }
}

impl Drop for RuntimeCore {
    fn drop(&mut self) {
        if self.closed || self.handle == 0 {
            return;
        }
        unsafe {
            let _ = (self.shutdown)(self.handle, 10_000);
            let _ = (self.destroy)(self.handle);
        }
        self.closed = true;
        self.handle = 0;
    }
}

impl RuntimeCore {
    fn load(path: &Path) -> Result<Self, String> {
        let library = unsafe { Library::new(path) }
            .map_err(|error| format!("load runtime library '{}': {error}", path.display()))?;
        unsafe {
            let abi_version = *library
                .get::<AbiVersionFn>(b"agent_runtime_abi_version_v1\0")
                .map_err(|error| format!("load abi_version symbol: {error}"))?;
            let version = *library
                .get::<StaticStringFn>(b"agent_runtime_version_v1\0")
                .map_err(|error| format!("load version symbol: {error}"))?;
            let create = *library
                .get::<CreateFn>(b"agent_runtime_create_v1\0")
                .map_err(|error| format!("load create symbol: {error}"))?;
            let start = *library
                .get::<StartFn>(b"agent_runtime_start_v1\0")
                .map_err(|error| format!("load start symbol: {error}"))?;
            let invoke_fn = *library
                .get::<InvokeFn>(b"agent_runtime_invoke_v1\0")
                .map_err(|error| format!("load invoke symbol: {error}"))?;
            let next_event = *library
                .get::<NextEventFn>(b"agent_runtime_next_event_v1\0")
                .map_err(|error| format!("load next_event symbol: {error}"))?;
            let shutdown = *library
                .get::<ShutdownFn>(b"agent_runtime_shutdown_v1\0")
                .map_err(|error| format!("load shutdown symbol: {error}"))?;
            let destroy = *library
                .get::<DestroyFn>(b"agent_runtime_destroy_v1\0")
                .map_err(|error| format!("load destroy symbol: {error}"))?;
            let last_error = *library
                .get::<StaticStringFn>(b"agent_runtime_last_error_json_v1\0")
                .map_err(|error| format!("load last_error symbol: {error}"))?;
            let free_string = *library
                .get::<FreeStringFn>(b"agent_runtime_free_string_v1\0")
                .map_err(|error| format!("load free_string symbol: {error}"))?;

            let actual_abi = abi_version();
            if actual_abi != ABI_VERSION {
                return Err(format!(
                    "incompatible runtime ABI: expected {ABI_VERSION}, got {actual_abi}"
                ));
            }

            let version_text = borrowed_string(version());
            if version_text.trim_start_matches('v') != ORBIT_RUNTIME_VERSION {
                return Err(format!(
                    "Orbit Runtime version mismatch: expected {ORBIT_RUNTIME_VERSION}, got {version_text}"
                ));
            }
            Ok(Self {
                _library: library,
                handle: 0,
                version: version_text,
                create,
                start,
                invoke_fn,
                next_event,
                shutdown,
                destroy,
                last_error,
                free_string,
                closed: false,
            })
        }
    }

    fn create_runtime(&mut self, create_options: &str) -> Result<(), String> {
        if self.handle != 0 {
            unsafe {
                let _ = (self.destroy)(self.handle);
            }
            self.handle = 0;
        }
        let input = cstring(create_options.to_string())?;
        let mut handle = 0;
        let code = unsafe { (self.create)(input.as_ptr(), &mut handle) };
        self.raise_for_code(code, None)?;
        self.handle = handle;
        Ok(())
    }

    fn start(&mut self) -> Result<(), String> {
        let code = unsafe { (self.start)(self.handle) };
        self.raise_for_code(code, None)
    }

    fn invoke(&mut self, command_type: &str, payload: Value) -> Result<Value, String> {
        let request = json!({
            "schema": "agent-runtime-command/v1",
            "type": command_type,
            "payload": payload
        });
        let request_text = request.to_string();
        let request = cstring(request_text.clone())?;
        let mut output: *mut c_char = std::ptr::null_mut();
        let code = unsafe { (self.invoke_fn)(self.handle, request.as_ptr(), &mut output) };
        let envelope = unsafe { self.take_json(output) };
        let error = envelope.get("error").cloned();
        if code != OK {
            eprintln!(
                "[reidom-tauri] runtime invoke failed: command={command_type} code={code}"
            );
        }
        self.raise_for_code(code, error)?;
        Ok(envelope.get("result").cloned().unwrap_or(Value::Null))
    }

    fn event_reader(&self) -> RuntimeEventReader {
        RuntimeEventReader {
            handle: self.handle,
            next_event: self.next_event,
            last_error: self.last_error,
            free_string: self.free_string,
        }
    }

    fn raise_for_code(&self, code: c_int, error: Option<Value>) -> Result<(), String> {
        if code == OK {
            return Ok(());
        }
        let detail = error
            .map(|value| value.to_string())
            .unwrap_or_else(|| unsafe { borrowed_string((self.last_error)()) });
        Err(format!("RUNTIME call failed ({code}): {detail}"))
    }

    unsafe fn take_json(&self, pointer: *mut c_char) -> Value {
        if pointer.is_null() {
            return Value::Null;
        }
        let text = borrowed_string(pointer);
        (self.free_string)(pointer);
        serde_json::from_str(&text).unwrap_or_else(|_| json!({ "raw": text }))
    }
}

struct RuntimePaths {
    library_path: PathBuf,
    create_options: String,
    resources_path: PathBuf,
    llm_providers_path: Option<PathBuf>,
    agent_cluster_path: PathBuf,
}

impl RuntimePaths {
    fn discover(app: &AppHandle) -> Result<Self, String> {
        let paths = ReidomPaths::resolve(app)?;
        let create_options = json!({
            "schema": "agent-runtime-create-options/v1",
            "log_level": "info",
            "language": "zh-CN",
            "restore_policy": "strict",
            "data_dir": path_string(&paths.runtime_data_dir)
        })
        .to_string();
        Ok(Self {
            library_path: discover_library_path(&paths.resource_dir, &paths.repo_root)?,
            create_options,
            resources_path: paths.generated_resources_path,
            llm_providers_path: paths.llm_providers_path,
            agent_cluster_path: paths.agent_cluster_path,
        })
    }
}

fn discover_library_path(resource_dir: &Path, repo_root: &Path) -> Result<PathBuf, String> {
    for var in ["AGENT_RUNTIME_LIBRARY", "AGENT_RUNTIME_LIB"] {
        if let Ok(path) = env::var(var) {
            let path = PathBuf::from(path);
            if path.exists() {
                return Ok(path);
            }
        }
    }
    let ai_framework = env::var("AI_FRAMEWORK_DIR").ok().map(PathBuf::from);
    let mut candidates = vec![
        resource_dir.join("orbit").join("agent_runtime.dll"),
        resource_dir.join("orbit").join("libagent_runtime.so"),
        resource_dir.join("orbit").join("libagent_runtime.dylib"),
        repo_root.join("agent_runtime.dll"),
        repo_root
            .join("apps")
            .join("studio-web")
            .join("src-tauri")
            .join("agent_runtime.dll"),
    ];
    if let Some(root) = ai_framework {
        candidates.extend([
            root.join("target").join("debug").join("agent_runtime.dll"),
            root.join("target")
                .join("release")
                .join("agent_runtime.dll"),
            root.join("target")
                .join("debug")
                .join("libagent_runtime.so"),
            root.join("target")
                .join("release")
                .join("libagent_runtime.so"),
            root.join("target")
                .join("debug")
                .join("libagent_runtime.dylib"),
            root.join("target")
                .join("release")
                .join("libagent_runtime.dylib"),
        ]);
    }
    candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| "agent_runtime library not found; set AGENT_RUNTIME_LIBRARY".to_string())
}

pub(crate) fn read_llm_registration_json(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| format!("read '{}': {error}", path.display()))?;
    let replacements = [
        (
            "${LLM_API_KEY}",
            env::var("LLM_API_KEY").unwrap_or_default(),
        ),
        (
            "${LLM_BASE_URL}",
            env::var("LLM_BASE_URL").unwrap_or_else(|_| "https://api.openai.com/v1".to_string()),
        ),
        (
            "${LLM_MODEL_ID}",
            env::var("LLM_MODEL_ID").unwrap_or_else(|_| "gpt-4.1-mini".to_string()),
        ),
    ];
    let mut resolved = text;
    for (source, target) in replacements {
        resolved = resolved.replace(source, &target);
    }
    serde_json::from_str(&resolved).map_err(|error| format!("parse '{}': {error}", path.display()))
}

fn empty_llm_registration() -> Value {
    json!({
        "schema": "agent-runtime-llm-registration/v1",
        "id": "reidom-tauri-llm",
        "providers": [],
        "current_model_uid": null
    })
}

fn cstring(value: String) -> Result<CString, String> {
    CString::new(value).map_err(|_| "string contains an interior NUL byte".to_string())
}

unsafe fn borrowed_string(pointer: *const c_char) -> String {
    if pointer.is_null() {
        return String::new();
    }
    CStr::from_ptr(pointer).to_string_lossy().into_owned()
}
