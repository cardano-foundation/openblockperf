//! App settings (subset of Python AppSettings for the spike).

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum Network {
    #[default]
    Mainnet,
    Preprod,
    Preview,
}

impl Network {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Mainnet => "mainnet",
            Self::Preprod => "preprod",
            Self::Preview => "preview",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s.to_ascii_lowercase().as_str() {
            "mainnet" => Some(Self::Mainnet),
            "preprod" => Some(Self::Preprod),
            "preview" => Some(Self::Preview),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct NetworkConfig {
    pub magic: u64,
    pub starttime: i64,
}

impl Network {
    pub fn config(self) -> NetworkConfig {
        match self {
            Self::Mainnet => NetworkConfig {
                magic: 764_824_073,
                starttime: 1_591_566_291,
            },
            Self::Preprod => NetworkConfig {
                magic: 1,
                starttime: 1_654_041_600,
            },
            Self::Preview => NetworkConfig {
                magic: 2,
                starttime: 1_666_656_000,
            },
        }
    }
}

pub const DEFAULT_API_SRV: &str = "_obpf._tcp.network.cardano.org";

#[derive(Debug, Clone)]
pub struct AppSettings {
    pub api_url: Option<String>,
    pub api_srv: String,
    pub api_key: Option<String>,
    pub api_request_timeout_ms: u64,
    pub api_request_retries: u32,
    pub peer_event_stable_seconds: u64,
    pub peer_signal_ttl_seconds: u64,
    pub peer_prune_idle_seconds: u64,
    pub block_sample_check_interval: u64,
    pub min_age: u64,
    pub node_name: String,
    pub node_unit_name: String,
    pub tracer_log_file: Option<PathBuf>,
    pub node_kind: String,
    pub ekg_url: String,
    pub local_addr: String,
    pub local_port: u16,
    pub obfuscate_ips: Vec<String>,
    pub network: Network,
    pub local_metrics_enabled: bool,
    pub local_metrics_host: String,
    pub local_metrics_port: u16,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            api_url: None,
            api_srv: DEFAULT_API_SRV.to_string(),
            api_key: None,
            api_request_timeout_ms: 8000,
            api_request_retries: 2,
            peer_event_stable_seconds: 15,
            peer_signal_ttl_seconds: 1800,
            peer_prune_idle_seconds: 600,
            block_sample_check_interval: 2,
            min_age: 10,
            node_name: hostname::get()
                .ok()
                .and_then(|h| h.into_string().ok())
                .unwrap_or_else(|| "unknown".into()),
            node_unit_name: "cardano-tracer".into(),
            tracer_log_file: None,
            node_kind: "auto".into(),
            ekg_url: "http://localhost:12798/metrics".into(),
            local_addr: "0.0.0.0".into(),
            local_port: 3001,
            obfuscate_ips: vec![],
            network: Network::Mainnet,
            local_metrics_enabled: false,
            local_metrics_host: "127.0.0.1".into(),
            local_metrics_port: 14041,
        }
    }
}

impl AppSettings {
    pub fn network_config(&self) -> NetworkConfig {
        self.network.config()
    }
}
