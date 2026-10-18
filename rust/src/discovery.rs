//! DNS SRV discovery and ranked API edge selection.

use crate::config::AppSettings;
use anyhow::{anyhow, Context, Result};
use hickory_resolver::config::ResolverConfig;
use hickory_resolver::name_server::TokioConnectionProvider;
use hickory_resolver::Resolver;
use serde_json::Value;
use std::collections::HashSet;
use std::time::{Duration, Instant};
use tracing::debug;

pub const HEALTH_PROBE_TIMEOUT: Duration = Duration::from_secs(2);
pub const ENDPOINT_LIST_EXHAUSTED_PAUSE: Duration = Duration::from_secs(30);
pub const SRV_REFRESH_INTERVAL: Duration = Duration::from_secs(86400);

#[derive(Debug, Clone)]
pub struct SrvTarget {
    pub host: String,
    pub port: u16,
}

#[derive(Debug, Clone)]
pub struct EdgeEndpoint {
    pub base_url: String,
    pub host: Option<String>,
    pub port: Option<u16>,
    pub rtt_ms: Option<f64>,
    pub override_url: bool,
}

impl EdgeEndpoint {
    pub fn short_name(&self) -> String {
        if let Some(host) = &self.host {
            host.split('.').next().unwrap_or(host).to_string()
        } else if self.override_url {
            "override".into()
        } else {
            "unknown".into()
        }
    }
}

pub fn normalize_host(host: &str) -> String {
    host.trim_end_matches('.').to_string()
}

pub fn api_base_url(host: &str, port: u16, network: &str) -> String {
    format!(
        "https://{}:{}/{}/api/v0/",
        normalize_host(host),
        port,
        network
    )
}

pub fn health_url(host: &str, port: u16, network: &str) -> String {
    format!(
        "https://{}:{}/{}/api/health",
        normalize_host(host),
        port,
        network
    )
}

pub fn override_base_url(api_url: &str) -> String {
    format!("{}/", api_url.trim_end_matches('/'))
}

pub async fn resolve_srv_records(name: &str) -> Result<Vec<SrvTarget>> {
    let resolver = Resolver::builder_with_config(
        ResolverConfig::default(),
        TokioConnectionProvider::default(),
    )
    .build();
    let response = resolver
        .srv_lookup(name)
        .await
        .with_context(|| format!("SRV lookup failed for {name}"))?;
    let mut targets = Vec::new();
    let mut seen = HashSet::new();
    for rdata in response.iter() {
        let host = normalize_host(&rdata.target().to_ascii());
        let port = rdata.port();
        if seen.insert((host.clone(), port)) {
            targets.push(SrvTarget { host, port });
        }
    }
    if targets.is_empty() {
        return Err(anyhow!("No SRV records for {name}"));
    }
    Ok(targets)
}

pub async fn probe_health(
    client: &reqwest::Client,
    target: &SrvTarget,
    network: &str,
) -> Option<EdgeEndpoint> {
    let url = health_url(&target.host, target.port, network);
    let started = Instant::now();
    let response = client
        .get(&url)
        .timeout(HEALTH_PROBE_TIMEOUT)
        .send()
        .await
        .ok()?;
    let rtt_ms = started.elapsed().as_secs_f64() * 1000.0;
    if response.status() != reqwest::StatusCode::OK {
        debug!(%url, status = %response.status(), "Health probe non-200");
        return None;
    }
    let payload: Value = response.json().await.ok()?;
    if payload.get("status").and_then(|v| v.as_str()) != Some("healthy") {
        return None;
    }
    Some(EdgeEndpoint {
        base_url: api_base_url(&target.host, target.port, network),
        host: Some(target.host.clone()),
        port: Some(target.port),
        rtt_ms: Some(rtt_ms),
        override_url: false,
    })
}

pub async fn discover_endpoints(settings: &AppSettings) -> Result<Vec<EdgeEndpoint>> {
    let network = settings.network.as_str();
    if let Some(url) = &settings.api_url {
        return Ok(vec![EdgeEndpoint {
            base_url: override_base_url(url),
            host: None,
            port: None,
            rtt_ms: None,
            override_url: true,
        }]);
    }
    let targets = resolve_srv_records(&settings.api_srv).await?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_millis(settings.api_request_timeout_ms))
        .build()?;
    let mut healthy = Vec::new();
    for target in &targets {
        if let Some(ep) = probe_health(&client, target, network).await {
            healthy.push(ep);
        }
    }
    healthy.sort_by(|a, b| {
        a.rtt_ms
            .partial_cmp(&b.rtt_ms)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if healthy.is_empty() {
        return Err(anyhow!("No healthy API edges for {network}"));
    }
    Ok(healthy)
}

#[derive(Debug)]
pub struct EndpointPool {
    endpoints: Vec<EdgeEndpoint>,
    index: usize,
    service_mode: bool,
    settings: AppSettings,
    last_refresh: Instant,
}

impl EndpointPool {
    pub async fn new(settings: AppSettings, service_mode: bool) -> Result<Self> {
        let endpoints = discover_endpoints(&settings).await?;
        Ok(Self {
            endpoints,
            index: 0,
            service_mode,
            settings,
            last_refresh: Instant::now(),
        })
    }

    pub fn current(&self) -> Option<&EdgeEndpoint> {
        self.endpoints.get(self.index)
    }

    pub async fn ensure_ready(&mut self) -> Result<&EdgeEndpoint> {
        if self.endpoints.is_empty() || self.last_refresh.elapsed() > SRV_REFRESH_INTERVAL {
            self.refresh().await?;
        }
        self.endpoints
            .get(self.index)
            .ok_or_else(|| anyhow!("no endpoints"))
    }

    pub async fn refresh(&mut self) -> Result<()> {
        self.endpoints = discover_endpoints(&self.settings).await?;
        self.index = 0;
        self.last_refresh = Instant::now();
        Ok(())
    }

    pub async fn failover_from(&mut self, failed_base: &str) -> Result<&EdgeEndpoint> {
        if let Some(pos) = self
            .endpoints
            .iter()
            .position(|e| e.base_url == failed_base)
        {
            if pos == self.index {
                self.index += 1;
            }
        } else {
            self.index += 1;
        }
        if self.index >= self.endpoints.len() {
            if self.service_mode {
                tokio::time::sleep(ENDPOINT_LIST_EXHAUSTED_PAUSE).await;
                self.refresh().await?;
            } else {
                return Err(anyhow!("endpoint list exhausted"));
            }
        }
        self.endpoints
            .get(self.index)
            .ok_or_else(|| anyhow!("no endpoints after failover"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn url_helpers() {
        assert_eq!(
            api_base_url("edge.example.", 443, "mainnet"),
            "https://edge.example:443/mainnet/api/v0/"
        );
        assert_eq!(
            health_url("edge.example", 443, "preprod"),
            "https://edge.example:443/preprod/api/health"
        );
        assert_eq!(override_base_url("https://api.example/v0"), "https://api.example/v0/");
        assert_eq!(normalize_host("host.example."), "host.example");
    }
}
