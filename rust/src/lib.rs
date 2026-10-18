//! Experimental Rust OpenBlockperf client library.
//!
//! Python under `src/openblockperf/` remains the production source of truth
//! until the parity gate in `docs/rust-parity.md` passes.

pub mod apiclient;
pub mod app;
pub mod blocksample;
pub mod calidus;
pub mod config;
pub mod discovery;
pub mod events;
pub mod ip_obfuscate;
pub mod logreader;
pub mod peer;
pub mod peer_tracker;

pub use config::AppSettings;

/// Repository-root relative path to shared golden fixtures.
pub fn testdata_dir() -> std::path::PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("testdata")
}

use std::path::PathBuf;

pub fn load_testdata_json(relative: &str) -> anyhow::Result<serde_json::Value> {
    let path = testdata_dir().join(relative);
    let raw = std::fs::read_to_string(&path)?;
    Ok(serde_json::from_str(&raw)?)
}
