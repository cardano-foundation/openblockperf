//! HTTP API client for OpenBlockperf backend.

use crate::blocksample::BlockSample;
use crate::config::AppSettings;
use crate::discovery::EndpointPool;
use crate::events::PeerEventChangeType;
use crate::peer::{CloseReason, EventRole, PeerDirection};
use crate::peer_tracker::PeerReport;
use anyhow::{anyhow, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use tracing::{debug, warn};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeerEventRequest {
    pub at: DateTime<Utc>,
    pub direction: String,
    pub local_addr: String,
    pub local_port: i32,
    pub remote_addr: String,
    pub remote_port: i32,
    pub change_type: String,
    pub last_seen: DateTime<Utc>,
    pub last_state: String,
    pub duplex: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub n2n_version: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub diffusion_mode: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub peer_sharing: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub peras_support: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_generation: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub close_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub we_dialed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub event_role: Option<String>,
}

impl PeerEventRequest {
    pub fn from_report(report: &PeerReport) -> Self {
        Self {
            at: report.at,
            direction: report.direction.as_str().to_string(),
            local_addr: report.peer.local_addr.clone(),
            local_port: report.peer.local_port,
            remote_addr: report.peer.remote_addr.clone(),
            remote_port: report.remote_port,
            change_type: report.change_type.as_str().to_string(),
            last_seen: report.peer.last_signal.unwrap_or(report.at),
            last_state: report.state.clone(),
            duplex: false,
            n2n_version: report.peer.n2n_version,
            diffusion_mode: report.peer.diffusion_mode.clone(),
            peer_sharing: report.peer.peer_sharing.clone(),
            peras_support: report.peer.peras_support.clone(),
            node_generation: Some(report.node_generation),
            session_id: report.session_id.clone(),
            close_reason: report.close_reason.map(|r| r.as_str().to_string()),
            we_dialed: report.we_dialed,
            event_role: Some(report.event_role.as_str().to_string()),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClientInfoRequest {
    pub node_version: String,
    pub client_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IpProofResponse {
    pub token: String,
    pub ip: Option<String>,
    pub hostname: Option<String>,
    pub expires_at: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IpRegistrationResponse {
    pub status: String,
    pub msg: Option<String>,
    pub apikey: Option<String>,
    pub ipaddress: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegistrationChallengeResponse {
    pub challenge: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubmitSignedChallengeResponse {
    pub apikey: String,
}

pub struct ApiClient {
    settings: AppSettings,
    pool: EndpointPool,
    http: reqwest::Client,
}

impl ApiClient {
    pub async fn new(settings: AppSettings, service_mode: bool) -> Result<Self> {
        let pool = EndpointPool::new(settings.clone(), service_mode).await?;
        let http = reqwest::Client::builder()
            .timeout(std::time::Duration::from_millis(
                settings.api_request_timeout_ms,
            ))
            .build()?;
        Ok(Self {
            settings,
            pool,
            http,
        })
    }

    fn headers(&self) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();
        if let Some(key) = &self.settings.api_key {
            headers.insert("X-Api-Key", key.parse().unwrap());
        }
        headers.insert(
            "X-Hostname",
            self.settings.node_name.parse().unwrap_or_else(|_| {
                reqwest::header::HeaderValue::from_static("unknown")
            }),
        );
        headers
    }

    async fn post_json<T: Serialize, R: for<'de> Deserialize<'de>>(
        &mut self,
        path: &str,
        body: &T,
    ) -> Result<R> {
        let retries = 1 + self.settings.api_request_retries;
        let mut last_err = anyhow!("no attempt");
        for _ in 0..retries {
            let base = self.pool.ensure_ready().await?.base_url.clone();
            let url = format!("{base}{}", path.trim_start_matches('/'));
            match self
                .http
                .post(&url)
                .headers(self.headers())
                .json(body)
                .send()
                .await
            {
                Ok(resp) => {
                    let status = resp.status();
                    if status.is_success() {
                        return Ok(resp.json().await?);
                    }
                    if status.is_server_error() {
                        warn!(%url, %status, "API 5xx, failing over");
                        let _ = self.pool.failover_from(&base).await;
                        last_err = anyhow!("HTTP {status}");
                        continue;
                    }
                    let text = resp.text().await.unwrap_or_default();
                    return Err(anyhow!("HTTP {status}: {text}"));
                }
                Err(e) => {
                    debug!(%url, error = %e, "transport error");
                    let _ = self.pool.failover_from(&base).await;
                    last_err = e.into();
                }
            }
        }
        Err(last_err)
    }

    pub async fn submit_blocksample(&mut self, sample: &BlockSample) -> Result<()> {
        let _: serde_json::Value = self.post_json("submit/blocksample", sample).await?;
        Ok(())
    }

    pub async fn submit_peer_report(&mut self, report: &PeerReport) -> Result<()> {
        if !report.change_type.reportable() && report.event_role == EventRole::Temperature {
            return Ok(());
        }
        let body = PeerEventRequest::from_report(report);
        let _: serde_json::Value = self.post_json("submit/peerevent", &body).await?;
        Ok(())
    }

    pub async fn submit_clientinfo(&mut self, node_version: &str, client_version: &str) -> Result<()> {
        let body = ClientInfoRequest {
            node_version: node_version.to_string(),
            client_version: client_version.to_string(),
        };
        let _: serde_json::Value = self.post_json("submit/clientinfo", &body).await?;
        Ok(())
    }

    pub async fn request_calidus_challenge(&mut self, pool_id_bech32: &str) -> Result<String> {
        #[derive(Serialize)]
        struct Req<'a> {
            pool_id_bech32: &'a str,
        }
        let resp: RegistrationChallengeResponse = self
            .post_json(
                "registration/calidus/challenge",
                &Req { pool_id_bech32 },
            )
            .await?;
        Ok(resp.challenge)
    }

    pub async fn submit_calidus(
        &mut self,
        pool_id_bech32: &str,
        signature_hex: &str,
    ) -> Result<String> {
        #[derive(Serialize)]
        struct Req<'a> {
            pool_id_bech32: &'a str,
            signature_hex: &'a str,
        }
        let resp: SubmitSignedChallengeResponse = self
            .post_json(
                "registration/submit",
                &Req {
                    pool_id_bech32,
                    signature_hex,
                },
            )
            .await?;
        Ok(resp.apikey)
    }

    pub async fn refresh_endpoints(&mut self) -> Result<()> {
        self.pool.refresh().await
    }
}

// Keep enums referenced for serde stability / future payload builders.
#[allow(dead_code)]
fn _touch_enums() {
    let _ = PeerDirection::Inbound;
    let _ = CloseReason::Ttl;
    let _ = PeerEventChangeType::ColdWarm;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::load_testdata_json;

    #[test]
    fn api_fixture_shapes() {
        let proof = load_testdata_json("api/ip_proof_response.json").unwrap();
        let parsed: IpProofResponse = serde_json::from_value(proof).unwrap();
        assert_eq!(parsed.token, "proof-token-example");

        let reg = load_testdata_json("api/ip_registration_response.json").unwrap();
        let parsed: IpRegistrationResponse = serde_json::from_value(reg).unwrap();
        assert_eq!(parsed.status, "registered");
        assert_eq!(parsed.apikey.as_deref(), Some("test-api-key"));
    }
}
