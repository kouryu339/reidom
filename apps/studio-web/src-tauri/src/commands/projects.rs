use std::{fs, path::{Path, PathBuf}, sync::{Arc, Mutex}, time::{SystemTime, UNIX_EPOCH}};
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, State};
use super::SharedEngine;

static LIBRARY_LOCK: Mutex<()> = Mutex::new(());

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn independent_projects_and_backup() {
        let root = std::env::temp_dir().join(format!("reidom-library-test-{}", SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
        fs::create_dir_all(&root).unwrap();
        for id in ["song-a", "song-b"] {
            save(&root, &json!({"project":{"project_id":id,"name":id,"revision":1,"tracks":[]}})).unwrap();
        }
        save(&root, &json!({"project":{"project_id":"song-a","name":"changed","revision":2,"tracks":[]}})).unwrap();
        let a = root.join(format!("{}.json", key("song-a").unwrap()));
        let b = root.join(format!("{}.json", key("song-b").unwrap()));
        assert!(a.with_extension("bak").is_file());
        let value: Value = serde_json::from_slice(&fs::read(b).unwrap()).unwrap();
        assert_eq!(value["document"]["project"]["revision"], 1);
        assert!(!key("../outside").unwrap().contains('/'));
        assert!(key("").is_err());
        fs::remove_dir_all(root).unwrap();
    }
}

fn root(app: &AppHandle) -> Result<PathBuf, String> {
    let path = app.path().app_data_dir().map_err(|e| e.to_string())?.join("projects").join("library");
    fs::create_dir_all(&path).map_err(|e| e.to_string())?;
    Ok(path)
}

fn key(id: &str) -> Result<String, String> {
    if id.is_empty() || id.len() > 128 { return Err("无效项目编号".into()); }
    Ok(id.bytes().map(|byte| format!("{byte:02x}")).collect())
}

fn save(root: &Path, exported: &Value) -> Result<Value, String> {
    let project = exported.get("project").ok_or("工程内容缺失")?;
    let id = project["project_id"].as_str().ok_or("工程编号缺失")?;
    let path = root.join(format!("{}.json", key(id)?));
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|e| e.to_string())?.as_millis() as u64;
    let entry = json!({"id":id,"name":project["name"],"updated_at":now,
        "track_count":project["tracks"].as_array().map_or(0, |v| v.len()),"document":exported});
    let temporary = path.with_extension("tmp");
    fs::write(&temporary, serde_json::to_vec(&entry).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    // Keep the last good file until the replacement has been completely written.
    let backup = path.with_extension("bak");
    if path.exists() {
        if backup.exists() { fs::remove_file(&backup).map_err(|e| e.to_string())?; }
        fs::rename(&path, &backup).map_err(|e| e.to_string())?;
    }
    if let Err(error) = fs::rename(&temporary, &path) {
        if backup.exists() { let _ = fs::rename(&backup, &path); }
        return Err(error.to_string());
    }
    Ok(json!({"saved":true,"id":id,"revision":project["revision"]}))
}

#[tauri::command]
pub async fn project_library(app: AppHandle, state: State<'_, SharedEngine>, action: String, id: Option<String>) -> Result<Value, String> {
    let root = root(&app)?;
    let engine = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = LIBRARY_LOCK.lock().map_err(|_| "项目库暂不可用")?;
        if action == "list" {
            let mut items = Vec::new();
            for file in fs::read_dir(&root).map_err(|e| e.to_string())? {
                let path = file.map_err(|e| e.to_string())?.path();
                if path.extension().and_then(|s| s.to_str()) != Some("json") { continue; }
                let mut value: Value = serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?).map_err(|e| format!("项目索引损坏：{e}"))?;
                value.as_object_mut().ok_or("项目索引格式错误")?.remove("document");
                items.push(value);
            }
            items.sort_by_key(|v| std::cmp::Reverse(v["updated_at"].as_u64().unwrap_or(0)));
            return Ok(json!(items));
        }
        let mut engine = engine.lock().map_err(|_| "音频引擎暂不可用")?;
        if action == "save" { return save(&root, &engine.call(json!({"method":"project.export_json"}))?); }
        if action != "open" { return Err("不支持的项目操作".into()); }
        let path = root.join(format!("{}.json", key(id.as_deref().ok_or("请选择项目")?)?));
        let entry: Value = serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        let target = entry["document"]["project"].clone();
        if !target.is_object() { return Err("项目文件内容缺失".into()); }
        save(&root, &engine.call(json!({"method":"project.export_json"}))?)?;
        engine.call(json!({"method":"project.import_json","source":"restore","project":target}))
    }).await.map_err(|e| e.to_string())?
}
