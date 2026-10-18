//! Log source readers (journalctl subprocess + file tail).

use anyhow::{anyhow, Context, Result};
use async_trait::async_trait;
use futures::stream::{self, BoxStream, StreamExt};
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use tokio::fs::File;
use tokio::io::{AsyncBufReadExt, AsyncSeekExt, BufReader, SeekFrom};
use tokio::process::{Child, Command};
use tokio::time::{sleep, Duration};
use tracing::{debug, warn};

const STARTUP_MARKER: &str = r#""ns":"Net.Server.Local.Started""#;

#[async_trait]
pub trait NodeLogReader: Send {
    async fn connect(&mut self) -> Result<()>;
    async fn close(&mut self) -> Result<()>;
    fn read_messages(&mut self) -> BoxStream<'_, Result<Value>>;
}

pub struct JournalCtlLogReader {
    unit: String,
    process: Option<Child>,
}

impl JournalCtlLogReader {
    pub fn new(unit: impl Into<String>) -> Self {
        Self {
            unit: unit.into(),
            process: None,
        }
    }
}

#[async_trait]
impl NodeLogReader for JournalCtlLogReader {
    async fn connect(&mut self) -> Result<()> {
        let child = Command::new("journalctl")
            .args([
                "-f",
                "--unit",
                &self.unit,
                "-o",
                "cat",
                "--no-pager",
                "--since",
                "now",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .with_context(|| format!("failed to spawn journalctl for {}", self.unit))?;
        self.process = Some(child);
        debug!(unit = %self.unit, "JournalCtlLogReader connected");
        Ok(())
    }

    async fn close(&mut self) -> Result<()> {
        if let Some(mut child) = self.process.take() {
            let _ = child.kill().await;
        }
        Ok(())
    }

    fn read_messages(&mut self) -> BoxStream<'_, Result<Value>> {
        let Some(child) = self.process.as_mut() else {
            return stream::once(async { Err(anyhow!("journalctl not connected")) }).boxed();
        };
        let stdout = child.stdout.take();
        let Some(stdout) = stdout else {
            return stream::once(async { Err(anyhow!("journalctl stdout missing")) }).boxed();
        };
        let reader = BufReader::new(stdout);
        let lines = reader.lines();
        stream::unfold(lines, |mut lines| async move {
            match lines.next_line().await {
                Ok(Some(line)) => {
                    let line = line.trim().to_string();
                    if line.is_empty() {
                        return Some((Ok(Value::Null), lines));
                    }
                    match serde_json::from_str::<Value>(&line) {
                        Ok(v) => Some((Ok(v), lines)),
                        Err(e) => {
                            warn!(error = %e, "skip non-json journal line");
                            Some((Ok(Value::Null), lines))
                        }
                    }
                }
                Ok(None) => None,
                Err(e) => Some((Err(e.into()), lines)),
            }
        })
        .filter_map(|item| async move {
            match item {
                Ok(Value::Null) => None,
                other => Some(other),
            }
        })
        .boxed()
    }
}

pub struct FileLogReader {
    path: PathBuf,
    unit_filter: Option<String>,
    offset: u64,
    inode: Option<u64>,
}

impl FileLogReader {
    pub fn new(path: impl Into<PathBuf>, unit_filter: Option<String>) -> Self {
        Self {
            path: path.into(),
            unit_filter,
            offset: 0,
            inode: None,
        }
    }

    fn matches_unit(&self, value: &Value, raw: &str) -> bool {
        let Some(unit) = &self.unit_filter else {
            return true;
        };
        for key in ["unit", "syslog_identifier", "syslogIdentifier", "SYSLOG_IDENTIFIER"] {
            if let Some(v) = value.get(key).and_then(|v| v.as_str()) {
                if v == unit {
                    return true;
                }
            }
        }
        raw.contains(unit)
    }

    async fn file_meta(path: &Path) -> Result<(u64, u64)> {
        let meta = tokio::fs::metadata(path).await?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            Ok((meta.ino(), meta.len()))
        }
        #[cfg(not(unix))]
        {
            Ok((0, meta.len()))
        }
    }
}

#[async_trait]
impl NodeLogReader for FileLogReader {
    async fn connect(&mut self) -> Result<()> {
        let (inode, len) = Self::file_meta(&self.path).await?;
        self.inode = Some(inode);
        self.offset = len;
        debug!(path = %self.path.display(), "FileLogReader connected at EOF");
        Ok(())
    }

    async fn close(&mut self) -> Result<()> {
        Ok(())
    }

    fn read_messages(&mut self) -> BoxStream<'_, Result<Value>> {
        let path = self.path.clone();
        let unit = self.unit_filter.clone();
        let mut offset = self.offset;
        let mut inode = self.inode;
        stream::unfold((), move |_| {
            let path = path.clone();
            let unit = unit.clone();
            async move {
                loop {
                    sleep(Duration::from_millis(200)).await;
                    let meta = match Self::file_meta(&path).await {
                        Ok(m) => m,
                        Err(e) => return Some((Err(e), ())),
                    };
                    if let Some(prev) = inode {
                        if meta.0 != prev || meta.1 < offset {
                            // rotated or truncated
                            offset = 0;
                        }
                    }
                    inode = Some(meta.0);
                    if meta.1 <= offset {
                        continue;
                    }
                    let mut file = match File::open(&path).await {
                        Ok(f) => f,
                        Err(e) => return Some((Err(e.into()), ())),
                    };
                    if let Err(e) = file.seek(SeekFrom::Start(offset)).await {
                        return Some((Err(e.into()), ()));
                    }
                    let mut reader = BufReader::new(file);
                    let mut line = String::new();
                    match reader.read_line(&mut line).await {
                        Ok(0) => continue,
                        Ok(n) => {
                            offset += n as u64;
                            let trimmed = line.trim();
                            if trimmed.is_empty() {
                                continue;
                            }
                            match serde_json::from_str::<Value>(trimmed) {
                                Ok(v) => {
                                    let reader_tmp = FileLogReader {
                                        path: path.clone(),
                                        unit_filter: unit.clone(),
                                        offset: 0,
                                        inode: None,
                                    };
                                    if reader_tmp.matches_unit(&v, trimmed) {
                                        return Some((Ok(v), ()));
                                    }
                                }
                                Err(_) => continue,
                            }
                        }
                        Err(e) => return Some((Err(e.into()), ())),
                    }
                }
            }
        })
        .boxed()
    }
}

pub fn make_log_reader(
    tracer_log_file: Option<&Path>,
    node_unit_name: &str,
) -> Box<dyn NodeLogReader> {
    if let Some(path) = tracer_log_file {
        Box::new(FileLogReader::new(path, Some(node_unit_name.to_string())))
    } else {
        Box::new(JournalCtlLogReader::new(node_unit_name))
    }
}

/// Replay helper: scan a file for the startup marker (used in tests / offline).
pub async fn find_startup_offset(path: &Path) -> Result<Option<u64>> {
    let content = tokio::fs::read_to_string(path).await?;
    let mut last: Option<u64> = None;
    let mut offset = 0u64;
    for line in content.lines() {
        let line_len = line.len() as u64 + 1;
        if line.contains(STARTUP_MARKER) {
            last = Some(offset);
        }
        offset += line_len;
    }
    Ok(last)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::AsyncWriteExt;

    #[tokio::test]
    async fn file_reader_tails_new_json_line() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("node.json");
        tokio::fs::write(&path, b"").await.unwrap();
        let mut reader = FileLogReader::new(&path, None);
        reader.connect().await.unwrap();

        let mut file = tokio::fs::OpenOptions::new()
            .append(true)
            .open(&path)
            .await
            .unwrap();
        let line = r#"{"at":"2026-01-01T00:00:00Z","ns":"Net.Server.Remote.Started","data":{"kind":"test"},"host":"t"}"#;
        file.write_all(line.as_bytes()).await.unwrap();
        file.write_all(b"\n").await.unwrap();
        drop(file);

        let mut stream = reader.read_messages();
        let got = tokio::time::timeout(Duration::from_secs(3), stream.next())
            .await
            .expect("timeout")
            .expect("item")
            .unwrap();
        assert_eq!(got["ns"], "Net.Server.Remote.Started");
    }

    #[tokio::test]
    async fn startup_marker_offset() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("log.txt");
        let content = format!(
            "{}\n{marker}\nmore\n",
            r#"{"ns":"other"}"#,
            marker = STARTUP_MARKER
        );
        tokio::fs::write(&path, content).await.unwrap();
        let off = find_startup_offset(&path).await.unwrap();
        assert!(off.is_some());
    }
}
