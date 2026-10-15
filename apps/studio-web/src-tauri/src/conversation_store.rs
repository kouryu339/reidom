//! Local conversation checkpoints, isolated from musical project documents.
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

pub fn key(id: &str) -> Result<String, String> {
    if id.is_empty() || id.len() > 128 {
        return Err("无效会话或作品编号".into());
    }
    Ok(id.bytes().map(|byte| format!("{byte:02x}")).collect())
}

pub fn write_atomic(path: &Path, value: &Value) -> Result<(), String> {
    fs::create_dir_all(path.parent().ok_or("缺少保存目录")?).map_err(|e| e.to_string())?;
    let temporary = path.with_extension("tmp");
    fs::write(
        &temporary,
        serde_json::to_vec(value).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    fs::rename(temporary, path).map_err(|e| e.to_string())
}

pub struct ConversationStore {
    root: PathBuf,
    project_id: String,
}

impl ConversationStore {
    pub fn new(root: &Path, project_id: &str) -> Result<Self, String> {
        Ok(Self {
            root: root.join(key(project_id)?),
            project_id: project_id.into(),
        })
    }

    fn path(&self, id: &str, suffix: &str) -> Result<PathBuf, String> {
        Ok(self.root.join(format!("{}.{suffix}.json", key(id)?)))
    }

    pub fn contains(&self, id: &str) -> Result<bool, String> {
        Ok(self.path(id, "meta")?.is_file())
    }

    pub fn list(&self) -> Result<Vec<Value>, String> {
        if !self.root.exists() {
            return Ok(Vec::new());
        }
        let mut items = Vec::new();
        for entry in fs::read_dir(&self.root).map_err(|e| e.to_string())? {
            let path = entry.map_err(|e| e.to_string())?.path();
            if !path
                .file_name()
                .and_then(|s| s.to_str())
                .is_some_and(|s| s.ends_with(".meta.json"))
            {
                continue;
            }
            let meta = crate::app_paths::read_json(&path)
                .map_err(|_| "会话索引损坏，请检查本机历史文件")?;
            if meta["metadata"]["projectId"] != self.project_id {
                return Err("会话不属于当前作品".into());
            }
            items.push(meta);
        }
        items.sort_by_key(|v| std::cmp::Reverse(v["updatedAt"].as_u64().unwrap_or(0)));
        Ok(items)
    }

    pub fn save(&self, id: &str, snapshot: &Value, title: Option<&str>) -> Result<Value, String> {
        let metadata_path = self.path(id, "meta")?;
        let existing = if metadata_path.exists() {
            crate::app_paths::read_json(&metadata_path)?
        } else {
            Value::Null
        };
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|e| e.to_string())?
            .as_millis() as u64;
        let preview = snapshot["ledger"]
            .as_array()
            .and_then(|records| records.iter().find(|r| r["role"] == "user"))
            .and_then(|r| r["content"].as_str())
            .unwrap_or("")
            .chars()
            .take(100)
            .collect::<String>();
        let title = title
            .filter(|s| !s.trim().is_empty())
            .or_else(|| {
                existing["title"]
                    .as_str()
                    .filter(|s| *s != "新会话" || preview.is_empty())
            })
            .unwrap_or(if preview.is_empty() {
                "新会话"
            } else {
                &preview
            })
            .chars()
            .take(40)
            .collect::<String>();
        let metadata = json!({"archiveId":id,"runtimeConversationId":null,"title":title,"preview":preview,
            "createdAt":existing["createdAt"].as_u64().unwrap_or(now),"updatedAt":now,
            "status":"sealed","instanceState":"data_only","clusterId":"reidom-music",
            "metadata":{"projectId":self.project_id}});
        write_atomic(
            &self.path(id, "snapshot")?,
            &json!({"projectId":self.project_id,"snapshot":snapshot}),
        )?;
        write_atomic(&metadata_path, &metadata)?;
        Ok(metadata)
    }

    pub fn restore(&self, id: &str) -> Result<Value, String> {
        if !self.path(id, "meta")?.is_file() {
            return Err("找不到该会话历史".into());
        }
        let path = self.path(id, "snapshot")?;
        if fs::metadata(&path).map_err(|e| e.to_string())?.len() > 64 * 1024 * 1024 {
            return Err("会话文件过大，无法打开".into());
        }
        let value = crate::app_paths::read_json(&path)?;
        if value["projectId"] != self.project_id {
            return Err("会话不属于当前作品".into());
        }
        let snapshot = value.get("snapshot").ok_or("会话内容缺失")?;
        if snapshot["schema"] != "agent-runtime-conversation-snapshot/v1" {
            return Err("不支持的会话历史格式".into());
        }
        Ok(snapshot.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn checkpoints_are_project_scoped_and_replaceable() {
        let root = std::env::temp_dir().join(format!(
            "reidom-history-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let a = ConversationStore::new(&root, "song-a").unwrap();
        let b = ConversationStore::new(&root, "song-b").unwrap();
        let mut snapshot = json!({"schema":"agent-runtime-conversation-snapshot/v1","ledger":[{"role":"user","content":"写一首歌"}]});
        a.save("conv_a", &snapshot, None).unwrap();
        snapshot["model_uid"] = json!(1002);
        a.save("conv_a", &snapshot, Some("测试会话")).unwrap();
        assert_eq!(a.list().unwrap().len(), 1);
        assert_eq!(a.restore("conv_a").unwrap()["model_uid"], 1002);
        assert!(b.list().unwrap().is_empty());
        assert!(b.restore("conv_a").is_err());
        assert!(!key("../outside").unwrap().contains('/'));
        assert!(key("").is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
