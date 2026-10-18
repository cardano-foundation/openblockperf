//! OpenBlockperf CLI (experimental Rust binary).

use anyhow::{anyhow, Result};
use clap::{Parser, Subcommand};
use openblockperf::apiclient::ApiClient;
use openblockperf::app::{Blockperf, CLIENT_VERSION};
use openblockperf::calidus::sign_challenge_from_skey_file;
use openblockperf::config::{AppSettings, Network};
use std::path::PathBuf;
use tracing::info;
use tracing_subscriber::EnvFilter;

#[derive(Parser, Debug)]
#[command(name = "blockperf", version = CLIENT_VERSION, about = "OpenBlockperf client (Rust explore spike)")]
struct Cli {
    /// Path to config JSON/YAML (OPENBLOCKPERF_CONFIG)
    #[arg(long, env = "OPENBLOCKPERF_CONFIG")]
    config: Option<PathBuf>,

    #[arg(long, env = "OPENBLOCKPERF_NETWORK")]
    network: Option<String>,

    #[arg(long, env = "OPENBLOCKPERF_API_URL")]
    api_url: Option<String>,

    #[arg(long, env = "OPENBLOCKPERF_API_KEY")]
    api_key: Option<String>,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Print version
    Version,
    /// Run the long-lived telemetry service
    Run {
        #[arg(long, env = "OPENBLOCKPERF_NODE_UNIT_NAME")]
        node_unit_name: Option<String>,
        #[arg(long, env = "OPENBLOCKPERF_TRACER_LOG_FILE")]
        tracer_log_file: Option<PathBuf>,
    },
    /// Register via Calidus challenge signing
    RegisterCalidus {
        #[arg(long)]
        pool_id: String,
        #[arg(long)]
        calidus_skey: PathBuf,
    },
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive("info".parse()?))
        .init();

    let cli = Cli::parse();
    let mut settings = AppSettings::default();
    if let Some(net) = cli.network.as_deref().and_then(Network::parse) {
        settings.network = net;
    }
    if let Some(url) = cli.api_url {
        settings.api_url = Some(url);
    }
    if let Some(key) = cli.api_key {
        settings.api_key = Some(key);
    }
    if let Some(path) = &cli.config {
        apply_config_file(&mut settings, path)?;
    }

    match cli.command {
        Commands::Version => {
            println!("openblockperf {CLIENT_VERSION} (rust explore)");
            Ok(())
        }
        Commands::Run {
            node_unit_name,
            tracer_log_file,
        } => {
            if let Some(u) = node_unit_name {
                settings.node_unit_name = u;
            }
            if let Some(p) = tracer_log_file {
                settings.tracer_log_file = Some(p);
            }
            info!(
                network = settings.network.as_str(),
                node = %settings.node_name,
                "starting rust blockperf"
            );
            Blockperf::new(settings).start().await
        }
        Commands::RegisterCalidus {
            pool_id,
            calidus_skey,
        } => {
            let mut api = ApiClient::new(settings, false).await?;
            let challenge = api.request_calidus_challenge(&pool_id).await?;
            let signature = sign_challenge_from_skey_file(&calidus_skey, &challenge)?;
            let apikey = api.submit_calidus(&pool_id, &signature).await?;
            println!("API_KEY={apikey}");
            Ok(())
        }
    }
}

fn apply_config_file(settings: &mut AppSettings, path: &PathBuf) -> Result<()> {
    let raw = std::fs::read_to_string(path)?;
    let value: serde_json::Value = serde_json::from_str(&raw)
        .or_else(|_| serde_json::from_str(&raw.replace('\t', " ")))
        .map_err(|e| anyhow!("config parse failed: {e}"))?;
    if let Some(s) = value.get("api_url").and_then(|v| v.as_str()) {
        settings.api_url = Some(s.to_string());
    }
    if let Some(s) = value.get("api_key").and_then(|v| v.as_str()) {
        settings.api_key = Some(s.to_string());
    }
    if let Some(s) = value.get("api_srv").and_then(|v| v.as_str()) {
        settings.api_srv = s.to_string();
    }
    if let Some(s) = value.get("network").and_then(|v| v.as_str()) {
        settings.network = Network::parse(s).ok_or_else(|| anyhow!("bad network {s}"))?;
    }
    if let Some(s) = value.get("node_name").and_then(|v| v.as_str()) {
        settings.node_name = s.to_string();
    }
    if let Some(s) = value.get("node_unit_name").and_then(|v| v.as_str()) {
        settings.node_unit_name = s.to_string();
    }
    if let Some(s) = value.get("tracer_log_file").and_then(|v| v.as_str()) {
        settings.tracer_log_file = Some(PathBuf::from(s));
    }
    if let Some(s) = value.get("local_addr").and_then(|v| v.as_str()) {
        settings.local_addr = s.to_string();
    }
    if let Some(n) = value.get("local_port").and_then(|v| v.as_u64()) {
        settings.local_port = n as u16;
    }
    Ok(())
}
