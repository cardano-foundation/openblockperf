//! Log event parsing for Haskell cardano-node tracer JSON.

use crate::peer::{ConnectionId, PeerDirection, PeerState};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde_json::Value;
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum EventError {
    #[error("unknown namespace: {0}")]
    UnknownNamespace(String),
    #[error("invalid event data: {0}")]
    InvalidData(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PeerEventChangeType {
    ColdWarm,
    WarmHot,
    HotWarm,
    WarmCold,
    HotCooling,
    WarmCooling,
    CoolingCold,
}

impl PeerEventChangeType {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ColdWarm => "cold_to_warm",
            Self::WarmHot => "warm_to_hot",
            Self::HotWarm => "hot_to_warm",
            Self::WarmCold => "warm_to_cold",
            Self::HotCooling => "hot_to_cooling",
            Self::WarmCooling => "warm_to_cooling",
            Self::CoolingCold => "cooling_to_cold",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "cold_to_warm" => Some(Self::ColdWarm),
            "warm_to_hot" => Some(Self::WarmHot),
            "hot_to_warm" => Some(Self::HotWarm),
            "warm_to_cold" => Some(Self::WarmCold),
            "hot_to_cooling" => Some(Self::HotCooling),
            "warm_to_cooling" => Some(Self::WarmCooling),
            "cooling_to_cold" => Some(Self::CoolingCold),
            _ => None,
        }
    }

    pub fn reportable(self) -> bool {
        matches!(
            self,
            Self::ColdWarm | Self::WarmHot | Self::HotWarm | Self::WarmCold
        )
    }
}

#[derive(Debug, Clone)]
pub struct Endpoints {
    pub local_addr: String,
    pub local_port: i32,
    pub remote_addr: String,
    pub remote_port: i32,
}

#[derive(Debug, Clone)]
pub struct DownloadedHeaderEvent {
    pub at: DateTime<Utc>,
    pub ns: String,
    pub host: String,
    pub block_hash: String,
    pub block_number: i64,
    pub slot: i64,
    pub endpoints: Endpoints,
}

#[derive(Debug, Clone)]
pub struct SendFetchRequestEvent {
    pub at: DateTime<Utc>,
    pub ns: String,
    pub host: String,
    pub block_hash: String,
    pub endpoints: Endpoints,
}

#[derive(Debug, Clone)]
pub struct CompletedBlockFetchEvent {
    pub at: DateTime<Utc>,
    pub ns: String,
    pub host: String,
    pub block_hash: String,
    pub block_size: i64,
    pub delay: f64,
    pub endpoints: Endpoints,
}

#[derive(Debug, Clone)]
pub struct ChainAdoptEvent {
    pub at: DateTime<Utc>,
    pub ns: String,
    pub host: String,
    pub block_hash: String,
    pub switched_fork: bool,
}

#[derive(Debug, Clone)]
pub struct HandshakeSuccessEvent {
    pub at: DateTime<Utc>,
    pub ns: String,
    pub host: String,
    pub endpoints: Endpoints,
    pub n2n_version: Option<i32>,
    pub diffusion_mode: Option<String>,
    pub peer_sharing: Option<String>,
    pub peras_support: Option<String>,
}

#[derive(Debug, Clone)]
pub struct PeerEvent {
    pub at: DateTime<Utc>,
    pub ns: String,
    pub host: String,
    pub state: PeerState,
    pub direction: PeerDirection,
    pub endpoints: Endpoints,
    pub change_type: PeerEventChangeType,
}

#[derive(Debug, Clone)]
pub struct NetworkLifecycleEvent {
    pub at: DateTime<Utc>,
    pub ns: String,
    pub host: String,
    pub start: bool,
}

#[derive(Debug, Clone)]
pub enum ParsedEvent {
    DownloadedHeader(DownloadedHeaderEvent),
    SendFetchRequest(SendFetchRequestEvent),
    CompletedBlockFetch(CompletedBlockFetchEvent),
    ChainAdopt(ChainAdoptEvent),
    HandshakeSuccess(HandshakeSuccessEvent),
    Peer(PeerEvent),
    NetworkLifecycle(NetworkLifecycleEvent),
    Ignored,
}

fn parse_at(v: &Value) -> Result<DateTime<Utc>, EventError> {
    let s = v
        .as_str()
        .ok_or_else(|| EventError::InvalidData("at is not a string".into()))?;
    // chrono does not accept 9-digit fractional seconds; truncate to micros.
    let normalized = normalize_iso8601(s);
    DateTime::parse_from_rfc3339(&normalized)
        .map(|dt| dt.with_timezone(&Utc))
        .map_err(|e| EventError::InvalidData(format!("bad at: {e}")))
}

fn normalize_iso8601(s: &str) -> String {
    // "2025-09-12T16:51:39.269022269Z" -> micros
    if let Some(dot) = s.find('.') {
        let (head, rest) = s.split_at(dot + 1);
        let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
        let tz = &rest[digits.len()..];
        let micros = if digits.len() >= 6 {
            digits[..6].to_string()
        } else {
            format!("{digits:0<6}")
        };
        format!("{head}{micros}{tz}")
    } else {
        s.to_string()
    }
}

fn peer_string_endpoints(data: &Value) -> Result<Endpoints, EventError> {
    let conn = data
        .pointer("/peer/connectionId")
        .and_then(|v| v.as_str())
        .ok_or_else(|| EventError::InvalidData("missing peer.connectionId".into()))?;
    let id = ConnectionId::parse(conn).map_err(|e| EventError::InvalidData(e.to_string()))?;
    Ok(Endpoints {
        local_addr: id.local_addr,
        local_port: id.local_port,
        remote_addr: id.remote_addr,
        remote_port: id.remote_port,
    })
}

fn structured_endpoints(data: &Value) -> Result<Endpoints, EventError> {
    let local = data
        .pointer("/connectionId/localAddress")
        .ok_or_else(|| EventError::InvalidData("missing localAddress".into()))?;
    let remote = data
        .pointer("/connectionId/remoteAddress")
        .ok_or_else(|| EventError::InvalidData("missing remoteAddress".into()))?;
    Ok(Endpoints {
        local_addr: json_str(local, "address")?,
        local_port: json_port(local, "port")?,
        remote_addr: json_str(remote, "address")?,
        remote_port: json_port(remote, "port")?,
    })
}

fn json_str(obj: &Value, key: &str) -> Result<String, EventError> {
    obj.get(key)
        .and_then(|v| v.as_str().map(|s| s.to_string()).or_else(|| v.as_i64().map(|n| n.to_string())))
        .ok_or_else(|| EventError::InvalidData(format!("missing {key}")))
}

fn json_port(obj: &Value, key: &str) -> Result<i32, EventError> {
    let v = obj
        .get(key)
        .ok_or_else(|| EventError::InvalidData(format!("missing {key}")))?;
    if let Some(n) = v.as_i64() {
        return Ok(n as i32);
    }
    if let Some(s) = v.as_str() {
        return s
            .parse()
            .map_err(|_| EventError::InvalidData(format!("bad port {s}")));
    }
    Err(EventError::InvalidData(format!("bad port type for {key}")))
}

fn envelope(raw: &Value) -> Result<(DateTime<Utc>, String, String, &Value), EventError> {
    let at = parse_at(raw.get("at").unwrap_or(&Value::Null))?;
    let ns = raw
        .get("ns")
        .and_then(|v| v.as_str())
        .ok_or_else(|| EventError::InvalidData("missing ns".into()))?
        .to_string();
    let host = raw
        .get("host")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown")
        .to_string();
    let data = raw
        .get("data")
        .ok_or_else(|| EventError::InvalidData("missing data".into()))?;
    Ok((at, ns, host, data))
}

pub fn parse_event(raw: &Value) -> Result<ParsedEvent, EventError> {
    let (at, ns, host, data) = envelope(raw)?;
    match ns.as_str() {
        "ChainSync.Client.DownloadedHeader" => {
            let endpoints = peer_string_endpoints(data)?;
            Ok(ParsedEvent::DownloadedHeader(DownloadedHeaderEvent {
                at,
                ns,
                host,
                block_hash: json_str(data, "block")?,
                block_number: data
                    .get("blockNo")
                    .and_then(|v| v.as_i64())
                    .ok_or_else(|| EventError::InvalidData("blockNo".into()))?,
                slot: data
                    .get("slot")
                    .and_then(|v| v.as_i64())
                    .ok_or_else(|| EventError::InvalidData("slot".into()))?,
                endpoints,
            }))
        }
        "BlockFetch.Client.SendFetchRequest" => {
            let endpoints = peer_string_endpoints(data)?;
            Ok(ParsedEvent::SendFetchRequest(SendFetchRequestEvent {
                at,
                ns,
                host,
                block_hash: json_str(data, "head")?,
                endpoints,
            }))
        }
        "BlockFetch.Client.CompletedBlockFetch" => {
            let endpoints = peer_string_endpoints(data)?;
            Ok(ParsedEvent::CompletedBlockFetch(CompletedBlockFetchEvent {
                at,
                ns,
                host,
                block_hash: json_str(data, "block")?,
                block_size: data
                    .get("size")
                    .and_then(|v| v.as_i64())
                    .ok_or_else(|| EventError::InvalidData("size".into()))?,
                delay: data.get("delay").and_then(|v| v.as_f64()).unwrap_or(0.0),
                endpoints,
            }))
        }
        "ChainDB.AddBlockEvent.AddedToCurrentChain"
        | "ChainDB.AddBlockEvent.SwitchedToAFork" => {
            let newtip = json_str(data, "newtip")?;
            let block_hash = newtip
                .split('@')
                .next()
                .unwrap_or("")
                .to_string();
            Ok(ParsedEvent::ChainAdopt(ChainAdoptEvent {
                at,
                switched_fork: ns.contains("SwitchedToAFork"),
                ns,
                host,
                block_hash,
            }))
        }
        "Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess" => {
            let endpoints = structured_endpoints(data)?;
            let handler = data.get("connectionHandler").unwrap_or(&Value::Null);
            let opts = handler.get("agreedOptions").unwrap_or(&Value::Null);
            Ok(ParsedEvent::HandshakeSuccess(HandshakeSuccessEvent {
                at,
                ns,
                host,
                endpoints,
                n2n_version: handler.get("versionNumber").and_then(|v| v.as_i64()).map(|n| n as i32),
                diffusion_mode: opts.get("diffusionMode").and_then(|v| v.as_str()).map(str::to_string),
                peer_sharing: opts.get("peerSharing").and_then(|v| v.as_str()).map(str::to_string),
                peras_support: opts.get("perasSupport").and_then(|v| v.as_str()).map(str::to_string),
            }))
        }
        "Net.Server.Remote.Started"
        | "Net.Server.Local.Started"
        | "Startup.DiffusionInit" => Ok(ParsedEvent::NetworkLifecycle(NetworkLifecycleEvent {
            at,
            ns,
            host,
            start: true,
        })),
        "Net.ConnectionManager.Remote.Shutdown"
        | "Net.Server.Remote.Stopped"
        | "Net.Server.Local.Stopped" => Ok(ParsedEvent::NetworkLifecycle(NetworkLifecycleEvent {
            at,
            ns,
            host,
            start: false,
        })),
        "Net.PeerSelection.Actions.StatusChanged" => {
            Ok(ParsedEvent::Peer(parse_status_changed(at, ns, host, data)?))
        }
        ns if ns.starts_with("Net.InboundGovernor.Remote.")
            || ns.starts_with("Net.ConnectionManager.Remote.ConnectionHandler.Error")
            || ns.contains("PeerSelection.Selection.") =>
        {
            Ok(ParsedEvent::Peer(parse_simple_peer(at, ns.to_string(), host, data)?))
        }
        _ => Err(EventError::UnknownNamespace(ns)),
    }
}

fn parse_simple_peer(
    at: DateTime<Utc>,
    ns: String,
    host: String,
    data: &Value,
) -> Result<PeerEvent, EventError> {
    // Selection Done: peer.address / peer.port only
    if ns.contains("PeerSelection.Selection.") {
        let addr = data
            .pointer("/peer/address")
            .and_then(|v| v.as_str())
            .ok_or_else(|| EventError::InvalidData("selection peer.address".into()))?
            .to_string();
        let port = data
            .pointer("/peer/port")
            .and_then(|v| {
                v.as_i64()
                    .map(|n| n as i32)
                    .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
            })
            .ok_or_else(|| EventError::InvalidData("selection peer.port".into()))?;
        let (state, change) = selection_done_mapping(&ns)?;
        let local_addr = if addr.contains(':') {
            "::".to_string()
        } else {
            "0.0.0.0".to_string()
        };
        return Ok(PeerEvent {
            at,
            ns,
            host,
            state,
            direction: PeerDirection::Outbound,
            endpoints: Endpoints {
                local_addr,
                local_port: 0,
                remote_addr: addr,
                remote_port: port,
            },
            change_type: change,
        });
    }

    let endpoints = structured_endpoints(data)?;
    let direction = if ns.contains("ConnectionHandler.Error") {
        let ctx = data
            .pointer("/connectionHandler/context")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if ctx == "OutboundError" {
            PeerDirection::Outbound
        } else {
            PeerDirection::Inbound
        }
    } else if ns.contains(".Remote") {
        PeerDirection::Inbound
    } else {
        return Err(EventError::InvalidData("cannot infer direction".into()));
    };

    let (state, change_type) = ig_state_and_change(&ns)?;
    Ok(PeerEvent {
        at,
        ns,
        host,
        state,
        direction,
        endpoints,
        change_type,
    })
}

fn ig_state_and_change(ns: &str) -> Result<(PeerState, PeerEventChangeType), EventError> {
    let (state, change) = if ns.ends_with("MuxErrored")
        || ns.ends_with("ResponderErrored")
        || ns.ends_with("ConnectionHandler.Error")
        || ns.ends_with("DemotedToColdRemote")
    {
        (PeerState::Cold, PeerEventChangeType::WarmCold)
    } else if ns.ends_with("DemotedToWarmRemote") {
        (PeerState::Warm, PeerEventChangeType::HotWarm)
    } else if ns.ends_with("PromotedToHotRemote") {
        (PeerState::Hot, PeerEventChangeType::WarmHot)
    } else if ns.ends_with("PromotedToWarmRemote") {
        (PeerState::Warm, PeerEventChangeType::ColdWarm)
    } else {
        return Err(EventError::UnknownNamespace(ns.to_string()));
    };
    Ok((state, change))
}

fn selection_done_mapping(ns: &str) -> Result<(PeerState, PeerEventChangeType), EventError> {
    if ns.contains("PromoteCold") {
        Ok((PeerState::Warm, PeerEventChangeType::ColdWarm))
    } else if ns.contains("PromoteWarm") {
        Ok((PeerState::Hot, PeerEventChangeType::WarmHot))
    } else if ns.contains("DemoteHot") {
        Ok((PeerState::Warm, PeerEventChangeType::HotWarm))
    } else if ns.contains("DemoteWarm") {
        Ok((PeerState::Cold, PeerEventChangeType::WarmCold))
    } else {
        Err(EventError::UnknownNamespace(ns.to_string()))
    }
}

fn parse_status_changed(
    at: DateTime<Utc>,
    ns: String,
    host: String,
    data: &Value,
) -> Result<PeerEvent, EventError> {
    let body = data
        .get("peerStatusChangeType")
        .and_then(|v| v.as_str())
        .ok_or_else(|| EventError::InvalidData("peerStatusChangeType".into()))?;
    static TRANS: OnceLock<Regex> = OnceLock::new();
    static ADDR: OnceLock<Regex> = OnceLock::new();
    let trans = TRANS.get_or_init(|| Regex::new(r"(\w+)To(\w+)").unwrap());
    let addr_re = ADDR.get_or_init(|| Regex::new(r"(?:\[([^\]]+)\]|([^:\s]+)):(\d+)").unwrap());
    let caps = trans
        .captures(body)
        .ok_or_else(|| EventError::InvalidData(format!("bad transition: {body}")))?;
    let from_state = caps.get(1).unwrap().as_str();
    let to_state = caps.get(2).unwrap().as_str();
    let addrs: Vec<_> = addr_re.captures_iter(body).collect();
    if addrs.len() < 2 {
        return Err(EventError::InvalidData(format!("need 2 addrs: {body}")));
    }
    let local = addr_capture(&addrs[0]);
    let remote = addr_capture(&addrs[1]);
    let state = PeerState::parse(to_state)
        .ok_or_else(|| EventError::InvalidData(format!("bad state {to_state}")))?;
    let change_key = format!("{}_{}_to_{}", "", from_state, to_state)
        .to_ascii_lowercase()
        .replace("__", "");
    // cold_to_warm style
    let change_str = format!("{}_to_{}", from_state.to_ascii_lowercase(), to_state.to_ascii_lowercase());
    let change_type = PeerEventChangeType::parse(&change_str)
        .ok_or_else(|| EventError::InvalidData(format!("bad change {change_str} ({change_key})")))?;
    Ok(PeerEvent {
        at,
        ns,
        host,
        state,
        direction: PeerDirection::Outbound,
        endpoints: Endpoints {
            local_addr: local.0,
            local_port: local.1,
            remote_addr: remote.0,
            remote_port: remote.1,
        },
        change_type,
    })
}

fn addr_capture(caps: &regex::Captures<'_>) -> (String, i32) {
    let addr = caps
        .get(1)
        .or_else(|| caps.get(2))
        .map(|m| m.as_str().to_string())
        .unwrap_or_default();
    let port: i32 = caps
        .get(3)
        .and_then(|m| m.as_str().parse().ok())
        .unwrap_or(0);
    (addr, port)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::load_testdata_json;

    #[test]
    fn parse_blocksample_chain_fixtures() {
        let header = load_testdata_json("events/downloaded_header.json").unwrap();
        let ParsedEvent::DownloadedHeader(h) = parse_event(&header).unwrap() else {
            panic!("expected header");
        };
        assert_eq!(
            h.block_hash,
            "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1"
        );
        assert_eq!(h.endpoints.remote_addr, "167.235.223.34");

        let fetch = load_testdata_json("events/send_fetch_request.json").unwrap();
        assert!(matches!(parse_event(&fetch).unwrap(), ParsedEvent::SendFetchRequest(_)));

        let done = load_testdata_json("events/completed_block_fetch.json").unwrap();
        let ParsedEvent::CompletedBlockFetch(c) = parse_event(&done).unwrap() else {
            panic!("expected completed");
        };
        assert_eq!(c.block_size, 87654);

        let adopt = load_testdata_json("events/added_to_current_chain.json").unwrap();
        let ParsedEvent::ChainAdopt(a) = parse_event(&adopt).unwrap() else {
            panic!("expected adopt");
        };
        assert_eq!(
            a.block_hash,
            "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1"
        );
    }

    #[test]
    fn parse_handshake_and_promote() {
        let hs = load_testdata_json("events/handshake_success.json").unwrap();
        let ParsedEvent::HandshakeSuccess(e) = parse_event(&hs).unwrap() else {
            panic!("hs");
        };
        assert_eq!(e.n2n_version, Some(14));
        assert_eq!(e.endpoints.remote_addr, "203.0.113.10");

        let warm = load_testdata_json("events/promoted_to_warm_remote.json").unwrap();
        let ParsedEvent::Peer(p) = parse_event(&warm).unwrap() else {
            panic!("peer");
        };
        assert_eq!(p.state, PeerState::Warm);
        assert_eq!(p.direction, PeerDirection::Inbound);
    }

    #[test]
    fn parse_status_changed_just() {
        let raw = load_testdata_json("events/status_changed_cold_to_warm_just.json").unwrap();
        let ParsedEvent::Peer(p) = parse_event(&raw).unwrap() else {
            panic!("peer");
        };
        assert_eq!(p.change_type, PeerEventChangeType::ColdWarm);
        assert_eq!(p.endpoints.remote_addr, "203.0.113.10");
        assert_eq!(p.direction, PeerDirection::Outbound);
    }
}
