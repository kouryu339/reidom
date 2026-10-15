use std::env;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde_json::{json, Value};

const DEFAULT_PORT: u16 = 50_120;
const CONNECT_TIMEOUT: Duration = Duration::from_millis(500);

pub struct ToolServiceState {
    child: Option<Child>,
    executable: PathBuf,
    engine_endpoint: String,
    port: u16,
    start_error: Option<String>,
}

impl ToolServiceState {
    pub fn start(repo_root: &Path) -> Self {
        let port = env::var("REIDOM_MIDI_TOOL_PORT")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_PORT);
        let mut state = Self {
            child: None,
            executable: resolve_executable(repo_root),
            engine_endpoint: env::var("REIDOM_ENGINE_ENDPOINT")
                .unwrap_or_else(|_| "127.0.0.1:47120".to_string()),
            port,
            start_error: None,
        };
        if let Err(error) = state.ensure_running() {
            state.start_error = Some(error);
        }
        state
    }

    pub fn ensure_running(&mut self) -> Result<(), String> {
        if self.is_listening() {
            self.start_error = None;
            return Ok(());
        }
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        if !self.executable.is_file() {
            return Err(format!(
                "MIDI tool service executable not found: {}",
                self.executable.display()
            ));
        }
        let mut command = Command::new(&self.executable);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let child = command
            .env("REIDOM_MIDI_TOOL_PORT", self.port.to_string())
            .env("REIDOM_ENGINE_ENDPOINT", &self.engine_endpoint)
            .env("REIDOM_PARENT_PID", std::process::id().to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| format!("start MIDI tool service: {error}"))?;
        self.child = Some(child);

        for _ in 0..50 {
            if self.is_listening() {
                self.start_error = None;
                return Ok(());
            }
            if let Some(child) = self.child.as_mut() {
                if let Ok(Some(status)) = child.try_wait() {
                    return Err(format!("MIDI tool service exited during startup: {status}"));
                }
            }
            thread::sleep(Duration::from_millis(100));
        }
        Err("MIDI tool service did not become ready within 5 seconds".to_string())
    }

    pub fn status(&mut self) -> Value {
        let healthy = self.is_listening();
        json!({
            "healthy": healthy,
            "endpoint": self.address().to_string(),
            "executable": self.executable,
            "diagnostic": if healthy { None } else { self.start_error.as_deref() },
        })
    }

    fn is_listening(&self) -> bool {
        TcpStream::connect_timeout(&self.address(), CONNECT_TIMEOUT).is_ok()
    }

    fn address(&self) -> SocketAddr {
        SocketAddr::from(([127, 0, 0, 1], self.port))
    }
}

impl Drop for ToolServiceState {
    fn drop(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

pub fn spawn_supervisor(service: Arc<Mutex<ToolServiceState>>) {
    thread::spawn(move || loop {
        if let Ok(mut service) = service.lock() {
            if let Err(error) = service.ensure_running() {
                service.start_error = Some(error);
            }
        }
        thread::sleep(Duration::from_secs(2));
    });
}

fn resolve_executable(repo_root: &Path) -> PathBuf {
    if let Some(path) = env::var_os("REIDOM_MIDI_TOOL_PATH") {
        return PathBuf::from(path);
    }
    let installed = env::current_exe().ok().and_then(|path| {
        path.parent()
            .map(|parent| parent.join("reidom-midi-tools.exe"))
    });
    let candidates = [
        installed.unwrap_or_default(),
        repo_root
            .join("apps")
            .join("studio-web")
            .join("src-tauri")
            .join("binaries")
            .join("reidom-midi-tools-x86_64-pc-windows-msvc.exe"),
        repo_root
            .join("services")
            .join("midi-tools")
            .join("dist")
            .join("reidom-midi-tools.exe"),
    ];
    candidates
        .into_iter()
        .find(|path| path.is_file())
        .unwrap_or_else(|| repo_root.join("services/midi-tools/dist/reidom-midi-tools.exe"))
}
