//! Peer identity, direction, temperature, and connectionId parsing.

use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const EPHEMERAL_PORT_MIN: i32 = 32768;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum PeerDirection {
    Inbound,
    Outbound,
}

impl PeerDirection {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Inbound => "inbound",
            Self::Outbound => "outbound",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum PeerState {
    Unknown,
    Unconnected,
    Cold,
    Warm,
    Hot,
    Cooling,
}

impl PeerState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Unknown => "Unknown",
            Self::Unconnected => "Unconnected",
            Self::Cold => "Cold",
            Self::Warm => "Warm",
            Self::Hot => "Hot",
            Self::Cooling => "Cooling",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "Unknown" => Some(Self::Unknown),
            "Unconnected" => Some(Self::Unconnected),
            "Cold" => Some(Self::Cold),
            "Warm" => Some(Self::Warm),
            "Hot" => Some(Self::Hot),
            "Cooling" => Some(Self::Cooling),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventRole {
    Open,
    Temperature,
    Close,
    NodeRestart,
}

impl EventRole {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Temperature => "temperature",
            Self::Close => "close",
            Self::NodeRestart => "node_restart",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CloseReason {
    IgMuxError,
    IgResponderError,
    HandlerError,
    DemotedCold,
    CoolingToCold,
    NodeRestart,
    Ttl,
}

impl CloseReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::IgMuxError => "ig_mux_error",
            Self::IgResponderError => "ig_responder_error",
            Self::HandlerError => "handler_error",
            Self::DemotedCold => "demoted_cold",
            Self::CoolingToCold => "cooling_to_cold",
            Self::NodeRestart => "node_restart",
            Self::Ttl => "ttl",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConnectionId {
    pub local_addr: String,
    pub local_port: i32,
    pub remote_addr: String,
    pub remote_port: i32,
}

#[derive(Debug, Error)]
pub enum ConnectionIdError {
    #[error("connectionId is not a string")]
    NotString,
    #[error("invalid connectionId format: {0}")]
    Invalid(String),
}

impl ConnectionId {
    pub fn parse(data: &str) -> Result<Self, ConnectionIdError> {
        let (local_str, remote_str) = data
            .split_once(' ')
            .ok_or_else(|| ConnectionIdError::Invalid(data.to_string()))?;
        let (local_addr, local_port) = parse_address_port(local_str)?;
        let (remote_addr, remote_port) = parse_address_port(remote_str)?;
        Ok(Self {
            local_addr,
            local_port,
            remote_addr,
            remote_port,
        })
    }
}

fn parse_address_port(addr_port: &str) -> Result<(String, i32), ConnectionIdError> {
    if let Some(rest) = addr_port.strip_prefix('[') {
        let bracket_end = rest
            .rfind(']')
            .ok_or_else(|| ConnectionIdError::Invalid(addr_port.to_string()))?;
        let address = rest[..bracket_end].to_string();
        let after = &rest[bracket_end + 1..];
        let port_str = after
            .strip_prefix(':')
            .ok_or_else(|| ConnectionIdError::Invalid(addr_port.to_string()))?;
        let port: i32 = port_str
            .parse()
            .map_err(|_| ConnectionIdError::Invalid(addr_port.to_string()))?;
        Ok((address, port))
    } else {
        let (address, port_str) = addr_port
            .rsplit_once(':')
            .ok_or_else(|| ConnectionIdError::Invalid(addr_port.to_string()))?;
        let port: i32 = port_str
            .parse()
            .map_err(|_| ConnectionIdError::Invalid(addr_port.to_string()))?;
        Ok((address.to_string(), port))
    }
}

pub fn is_ephemeral_port(port: i32) -> bool {
    port >= EPHEMERAL_PORT_MIN
}

pub fn submit_port(port: i32) -> i32 {
    if is_ephemeral_port(port) {
        0
    } else {
        port
    }
}

pub fn connection_key(local_addr: &str, local_port: i32, remote_addr: &str, remote_port: i32) -> String {
    format!("{local_addr}|{local_port}|{remote_addr}|{remote_port}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testdata_dir;

    #[test]
    fn parse_ipv4_from_testdata() {
        let raw = std::fs::read_to_string(testdata_dir().join("connectionid/ipv4.txt")).unwrap();
        let id = ConnectionId::parse(raw.trim()).unwrap();
        assert_eq!(id.local_addr, "172.0.118.125");
        assert_eq!(id.local_port, 30002);
        assert_eq!(id.remote_addr, "167.235.223.34");
        assert_eq!(id.remote_port, 5355);
    }

    #[test]
    fn parse_ipv6_from_testdata() {
        let raw = std::fs::read_to_string(testdata_dir().join("connectionid/ipv6.txt")).unwrap();
        let id = ConnectionId::parse(raw.trim()).unwrap();
        assert_eq!(id.local_addr, "2001:db8::1");
        assert_eq!(id.local_port, 3001);
        assert_eq!(id.remote_addr, "::1");
        assert_eq!(id.remote_port, 443);
    }
}
