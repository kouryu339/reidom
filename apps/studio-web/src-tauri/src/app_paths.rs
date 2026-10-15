use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};

pub struct ReidomPaths {
    pub repo_root: PathBuf,
    pub resource_dir: PathBuf,
    pub runtime_data_dir: PathBuf,
    pub generated_resources_path: PathBuf,
    pub llm_providers_path: Option<PathBuf>,
    pub agent_cluster_path: PathBuf,
}

impl ReidomPaths {
    pub fn resolve(app: &AppHandle) -> Result<Self, String> {
        let repo_root = repo_root()?;
        let resource_dir = app
            .path()
            .resource_dir()
            .map_err(|error| format!("resolve app resource dir: {error}"))?;
        let content_root = if resource_dir.join("config").join("resources.json").is_file() {
            resource_dir.clone()
        } else {
            repo_root.clone()
        };
        let app_data_dir = app
            .path()
            .app_data_dir()
            .map_err(|error| format!("resolve app data dir: {error}"))?;
        let runtime_data_dir = app_data_dir.join("runtime");
        fs::create_dir_all(&runtime_data_dir)
            .map_err(|error| format!("create runtime data dir: {error}"))?;

        let generated_resources_path = materialize_resources(&content_root, &runtime_data_dir)?;
        let user_llm = app_data_dir.join("config").join("llm-providers.json");
        let repo_llm = content_root.join("config").join("llm-providers.json");
        let repo_example_llm = content_root
            .join("config")
            .join("llm-providers.example.json");
        let llm_providers_path = first_existing([user_llm, repo_llm, repo_example_llm]);
        Ok(Self {
            repo_root: repo_root.clone(),
            resource_dir,
            runtime_data_dir,
            generated_resources_path,
            llm_providers_path,
            agent_cluster_path: content_root.join("config").join("agent-cluster.json"),
        })
    }
}

pub fn repo_root() -> Result<PathBuf, String> {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .ok_or_else(|| "could not resolve Reidom repository root".to_string())
}

pub fn path_string(path: &Path) -> String {
    path.display().to_string()
}

fn materialize_resources(content_root: &Path, runtime_data_dir: &Path) -> Result<PathBuf, String> {
    let source = content_root.join("config").join("resources.json");
    let mut value = read_json(&source)?;
    value["skills"]["root_dir"] = json!(path_string(&content_root.join("skills")));
    value["data"]["data_dir"] = json!(path_string(runtime_data_dir));
    value["data"]["logs_dir"] = json!(path_string(&runtime_data_dir.join("logs")));
    let documents = runtime_data_dir.parent().ok_or("missing user data parent")?.join("projects").join("ai");
    fs::create_dir_all(&documents).map_err(|e| e.to_string())?;
    value["grep"] = json!({"roots":[{"id":"projects", "path":path_string(&documents)}],
        "max_results":80, "max_output_bytes":32768, "max_file_bytes":16777216, "max_line_bytes":8192});
    let target = runtime_data_dir.join("generated-resources.json");
    write_json(&target, &value)?;
    Ok(target)
}

fn first_existing<const N: usize>(paths: [PathBuf; N]) -> Option<PathBuf> {
    paths.into_iter().find(|path| path.exists())
}

pub fn read_json(path: &Path) -> Result<Value, String> {
    let text =
        fs::read_to_string(path).map_err(|error| format!("read '{}': {error}", path.display()))?;
    serde_json::from_str(&text).map_err(|error| format!("parse '{}': {error}", path.display()))
}

fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("missing parent for '{}'", path.display()))?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("create '{}': {error}", parent.display()))?;
    let text = serde_json::to_string_pretty(value)
        .map_err(|error| format!("serialize '{}': {error}", path.display()))?;
    fs::write(path, text).map_err(|error| format!("write '{}': {error}", path.display()))
}
