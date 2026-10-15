use std::env;
use std::io::{Read, Write};
use std::net::{Shutdown, SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

const DEFAULT_PORT: u16 = 47_120;
const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
const START_TIMEOUT: Duration = Duration::from_secs(8);

pub struct EngineState {
    child: Option<Child>,
    executable: PathBuf,
    port: u16,
    start_error: Option<String>,
}

impl EngineState {
    pub fn start(repo_root: &Path) -> Self {
        let port = env::var("REIDOM_ENGINE_PORT")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_PORT);
        let executable = resolve_executable(repo_root);
        let mut state = Self {
            child: None,
            executable,
            port,
            start_error: None,
        };
        if state.request(json!({"method": "engine.health"})).is_ok() {
            return state;
        }
        if let Err(error) = state.spawn() {
            state.start_error = Some(error);
        }
        state
    }

    pub fn status(&mut self) -> Value {
        match self.request(json!({"method": "engine.health"})) {
            Ok(health) => json!({
                "healthy": true,
                "owner": "juce-engine",
                "endpoint": self.address().to_string(),
                "executable": self.executable,
                "health": health,
            }),
            Err(error) => json!({
                "healthy": false,
                "owner": "juce-engine",
                "endpoint": self.address().to_string(),
                "executable": self.executable,
                "diagnostic": self.start_error.as_deref().unwrap_or(&error),
            }),
        }
    }

    pub fn call(&mut self, request: Value) -> Result<Value, String> {
        self.ensure_running()?;
        self.request(request)
    }

    fn ensure_running(&mut self) -> Result<(), String> {
        if self.request(json!({"method": "engine.health"})).is_ok() {
            return Ok(());
        }
        self.spawn()
    }

    fn spawn(&mut self) -> Result<(), String> {
        if !self.executable.is_file() {
            return Err(format!(
                "JUCE engine executable not found: {}",
                self.executable.display()
            ));
        }
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        let port = self.port.to_string();
        let parent_pid = std::process::id().to_string();
        let mut command = Command::new(&self.executable);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let child = command
            .args(["--port", &port, "--parent-pid", &parent_pid])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| format!("start JUCE engine: {error}"))?;
        self.child = Some(child);
        let deadline = Instant::now() + START_TIMEOUT;
        while Instant::now() < deadline {
            if self.request(json!({"method": "engine.health"})).is_ok() {
                self.start_error = None;
                return Ok(());
            }
            if let Some(child) = self.child.as_mut() {
                if let Ok(Some(status)) = child.try_wait() {
                    return Err(format!("JUCE engine exited during startup: {status}"));
                }
            }
            thread::sleep(Duration::from_millis(80));
        }
        Err("JUCE engine did not become ready within 8 seconds".to_string())
    }

    fn request(&self, request: Value) -> Result<Value, String> {
        let mut stream = TcpStream::connect_timeout(&self.address(), CONNECT_TIMEOUT)
            .map_err(|error| format!("connect JUCE engine: {error}"))?;
        stream
            .set_read_timeout(Some(Duration::from_secs(10)))
            .map_err(|error| format!("configure JUCE engine read timeout: {error}"))?;
        let mut bytes = serde_json::to_vec(&request)
            .map_err(|error| format!("encode JUCE engine request: {error}"))?;
        bytes.push(b'\n');
        stream
            .write_all(&bytes)
            .map_err(|error| format!("write JUCE engine request: {error}"))?;
        stream
            .shutdown(Shutdown::Write)
            .map_err(|error| format!("finish JUCE engine request: {error}"))?;
        let mut response = String::new();
        stream
            .read_to_string(&mut response)
            .map_err(|error| format!("read JUCE engine response: {error}"))?;
        let value: Value = serde_json::from_str(&response)
            .map_err(|error| format!("decode JUCE engine response: {error}"))?;
        if value.get("ok").and_then(Value::as_bool) == Some(true) {
            return Ok(value.get("result").cloned().unwrap_or(Value::Null));
        }
        let message = value
            .pointer("/error/message")
            .and_then(Value::as_str)
            .unwrap_or("JUCE engine rejected the request");
        Err(message.to_string())
    }

    fn address(&self) -> SocketAddr {
        SocketAddr::from(([127, 0, 0, 1], self.port))
    }
}

impl Drop for EngineState {
    fn drop(&mut self) {
        if self.child.is_none() {
            return;
        }
        let _ = self.request(json!({"method": "engine.shutdown"}));
        if let Some(mut child) = self.child.take() {
            let deadline = Instant::now() + Duration::from_secs(2);
            while Instant::now() < deadline {
                if child.try_wait().ok().flatten().is_some() {
                    return;
                }
                thread::sleep(Duration::from_millis(40));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn resolve_executable(repo_root: &Path) -> PathBuf {
    if let Some(path) = env::var_os("REIDOM_ENGINE_PATH") {
        return PathBuf::from(path);
    }
    let installed = env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|parent| parent.join("reidom-engine.exe")));
    let candidates = [
        installed.unwrap_or_default(),
        repo_root.join("build/engine-ninja/reidom-engine_artefacts/Release/reidom-engine.exe"),
        repo_root.join("build/engine-ninja/reidom-engine_artefacts/Debug/reidom-engine.exe"),
        repo_root.join("engine/bin/reidom-engine.exe"),
    ];
    candidates
        .into_iter()
        .find(|path| path.is_file())
        .unwrap_or_else(|| repo_root.join("engine/bin/reidom-engine.exe"))
}
