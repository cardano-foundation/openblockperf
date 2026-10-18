//! Block sample aggregation from header / fetch / complete / adopt events.

use crate::config::AppSettings;
use crate::events::{
    ChainAdoptEvent, CompletedBlockFetchEvent, DownloadedHeaderEvent, ParsedEvent,
    SendFetchRequestEvent,
};
use chrono::{DateTime, TimeZone, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum BlockSampleError {
    #[error("{0}")]
    Event(String),
}

#[derive(Debug, Clone)]
pub struct HeaderAnnouncer {
    pub remote_addr: String,
    pub remote_port: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BlockSample {
    pub block_hash: String,
    pub block_number: i64,
    pub block_size: i64,
    pub block_g: f64,
    pub slot: i64,
    pub slot_time: String,
    pub header_remote_addr: String,
    pub header_remote_port: i32,
    pub header2_remote_addr: String,
    pub header2_remote_port: i32,
    pub header3_remote_addr: String,
    pub header3_remote_port: i32,
    pub header_delta: i64,
    pub block_remote_addr: String,
    pub block_remote_port: i32,
    pub block_request_delta: i64,
    pub block_response_delta: i64,
    pub block_adopt_delta: i64,
    pub local_addr: String,
    pub local_port: i32,
    pub magic: u64,
}

#[derive(Debug)]
pub struct BlockSampleGroup {
    pub block_hash: String,
    settings: AppSettings,
    pub block_number: Option<i64>,
    pub block_size: Option<i64>,
    pub block_g: f64,
    pub slot: Option<i64>,
    pub slot_time: Option<DateTime<Utc>>,
    block_header: Option<DownloadedHeaderEvent>,
    header_announcers: Vec<HeaderAnnouncer>,
    block_requested: Option<SendFetchRequestEvent>,
    block_completed: Option<CompletedBlockFetchEvent>,
    block_adopted: Option<ChainAdoptEvent>,
    fetch_events: Vec<SendFetchRequestEvent>,
    created_at: std::time::Instant,
}

impl BlockSampleGroup {
    pub fn new(block_hash: String, settings: AppSettings) -> Self {
        Self {
            block_hash,
            settings,
            block_number: None,
            block_size: None,
            block_g: 0.1,
            slot: None,
            slot_time: None,
            block_header: None,
            header_announcers: Vec::new(),
            block_requested: None,
            block_completed: None,
            block_adopted: None,
            fetch_events: Vec::new(),
            created_at: std::time::Instant::now(),
        }
    }

    pub fn add_parsed(&mut self, event: ParsedEvent) -> Result<(), BlockSampleError> {
        match event {
            ParsedEvent::DownloadedHeader(e) => self.add_header(e),
            ParsedEvent::SendFetchRequest(e) => {
                self.fetch_events.push(e);
                Ok(())
            }
            ParsedEvent::CompletedBlockFetch(e) => self.add_completed(e),
            ParsedEvent::ChainAdopt(e) => {
                if self.block_adopted.is_none() {
                    self.block_adopted = Some(e);
                }
                Ok(())
            }
            _ => Ok(()),
        }
    }

    fn add_header(&mut self, event: DownloadedHeaderEvent) -> Result<(), BlockSampleError> {
        let known: Vec<_> = self
            .header_announcers
            .iter()
            .map(|a| a.remote_addr.clone())
            .collect();
        if !known.contains(&event.endpoints.remote_addr) && self.header_announcers.len() < 3 {
            self.header_announcers.push(HeaderAnnouncer {
                remote_addr: event.endpoints.remote_addr.clone(),
                remote_port: event.endpoints.remote_port,
            });
        }
        match &self.block_header {
            Some(existing) if event.at < existing.at => self.block_header = Some(event.clone()),
            None => self.block_header = Some(event.clone()),
            _ => {}
        }
        if self.slot.is_none() {
            self.slot = Some(event.slot);
        }
        if self.slot_time.is_none() {
            let start = self.settings.network_config().starttime;
            self.slot_time = Some(Utc.timestamp_opt(start + event.slot, 0).single().unwrap());
        }
        if self.block_number.is_none() {
            self.block_number = Some(event.block_number);
        }
        Ok(())
    }

    fn add_completed(&mut self, event: CompletedBlockFetchEvent) -> Result<(), BlockSampleError> {
        if self.block_completed.is_none() {
            let fetch = self
                .fetch_events
                .iter()
                .find(|e| {
                    e.endpoints.remote_addr == event.endpoints.remote_addr
                        && e.endpoints.remote_port == event.endpoints.remote_port
                })
                .cloned()
                .ok_or_else(|| {
                    BlockSampleError::Event(format!(
                        "No send fetch found for {}",
                        event.block_hash
                    ))
                })?;
            self.block_requested = Some(fetch);
            self.block_completed = Some(event.clone());
        }
        if self.block_size.is_none() {
            self.block_size = Some(event.block_size);
        }
        Ok(())
    }

    pub fn is_complete(&self) -> bool {
        self.block_header.is_some()
            && self.block_requested.is_some()
            && self.block_completed.is_some()
            && self.block_adopted.is_some()
    }

    fn delta_ms(later: DateTime<Utc>, earlier: DateTime<Utc>) -> i64 {
        (later - earlier).num_milliseconds()
    }

    pub fn is_ok(&self) -> bool {
        if !self.is_complete() {
            return false;
        }
        let header = self.block_header.as_ref().unwrap();
        let req = self.block_requested.as_ref().unwrap();
        let done = self.block_completed.as_ref().unwrap();
        let adopt = self.block_adopted.as_ref().unwrap();
        let slot_time = self.slot_time.unwrap();
        let header_delta = Self::delta_ms(header.at, slot_time);
        let request_delta = Self::delta_ms(req.at, header.at);
        let response_delta = Self::delta_ms(done.at, req.at);
        let adopt_delta = Self::delta_ms(adopt.at, done.at);
        let block_number = self.block_number.unwrap_or(0);
        let slot = self.slot.unwrap_or(0);
        let block_size = self.block_size.unwrap_or(0);
        block_number > 0
            && slot > 0
            && (0..128).contains(&self.block_hash.len())
            && (0..10_000_000).contains(&block_size)
            && (-6000..600_000).contains(&header_delta)
            && (-6000..600_000).contains(&request_delta)
            && (-6000..600_000).contains(&response_delta)
            && (-6000..600_000).contains(&adopt_delta)
    }

    pub fn get_sample(&self) -> Option<BlockSample> {
        if !self.is_complete() {
            return None;
        }
        let header = self.block_header.as_ref().unwrap();
        let req = self.block_requested.as_ref().unwrap();
        let done = self.block_completed.as_ref().unwrap();
        let adopt = self.block_adopted.as_ref().unwrap();
        let slot_time = self.slot_time.unwrap();
        let a2 = self.header_announcers.get(1);
        let a3 = self.header_announcers.get(2);
        Some(BlockSample {
            block_hash: self.block_hash.clone(),
            block_number: self.block_number.unwrap(),
            block_size: self.block_size.unwrap(),
            block_g: self.block_g,
            slot: self.slot.unwrap(),
            slot_time: slot_time.to_rfc3339(),
            header_remote_addr: header.endpoints.remote_addr.clone(),
            header_remote_port: header.endpoints.remote_port,
            header2_remote_addr: a2.map(|a| a.remote_addr.clone()).unwrap_or_default(),
            header2_remote_port: a2.map(|a| a.remote_port).unwrap_or(0),
            header3_remote_addr: a3.map(|a| a.remote_addr.clone()).unwrap_or_default(),
            header3_remote_port: a3.map(|a| a.remote_port).unwrap_or(0),
            header_delta: Self::delta_ms(header.at, slot_time),
            block_remote_addr: done.endpoints.remote_addr.clone(),
            block_remote_port: done.endpoints.remote_port,
            block_request_delta: Self::delta_ms(req.at, header.at),
            block_response_delta: Self::delta_ms(done.at, req.at),
            block_adopt_delta: Self::delta_ms(adopt.at, done.at),
            local_addr: self.settings.local_addr.clone(),
            local_port: self.settings.local_port as i32,
            magic: self.settings.network_config().magic,
        })
    }

    pub fn age_seconds(&self) -> u64 {
        self.created_at.elapsed().as_secs()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::events::parse_event;
    use crate::load_testdata_json;

    #[test]
    fn blocksample_chain_from_testdata() {
        let settings = AppSettings::default();
        let hash = "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1";
        let mut group = BlockSampleGroup::new(hash.into(), settings);
        for name in [
            "events/downloaded_header.json",
            "events/send_fetch_request.json",
            "events/completed_block_fetch.json",
            "events/added_to_current_chain.json",
        ] {
            let raw = load_testdata_json(name).unwrap();
            let ev = parse_event(&raw).unwrap();
            group.add_parsed(ev).unwrap();
        }
        assert!(group.is_complete());
        // Same fixtures yield is_ok=false under mainnet genesis (header wall
        // clock is 2025, slot_time lands in 2023). Python matches that.
        assert!(!group.is_ok());
        let sample = group.get_sample().unwrap();
        assert_eq!(sample.block_hash, hash);
        assert_eq!(sample.block_number, 3600148);
        assert_eq!(sample.block_size, 87654);
        assert_eq!(sample.header_remote_addr, "167.235.223.34");
        assert_eq!(sample.magic, 764_824_073);
        assert!(sample.block_request_delta > 0);
        assert!(sample.block_response_delta > 0);
    }

    #[test]
    fn is_ok_bounds_with_aligned_slot_time() {
        let mut settings = AppSettings::default();
        // Force slot_time near the header timestamp so deltas stay in range.
        // header at ~ 2025-09-12T16:51:39, slot 91039899
        // starttime = header_unix - slot
        settings.network = crate::config::Network::Mainnet;
        // Patch via a local group after header: we recompute by using Preview
        // starttime won't help; instead inject by constructing sample math.
        let hash = "9d096f3fbe809021bcb78d6391751bf2725787380ea367bbe2fb93634ac613b1";
        let mut group = BlockSampleGroup::new(hash.into(), settings);
        for name in [
            "events/downloaded_header.json",
            "events/send_fetch_request.json",
            "events/completed_block_fetch.json",
            "events/added_to_current_chain.json",
        ] {
            let raw = load_testdata_json(name).unwrap();
            let ev = parse_event(&raw).unwrap();
            group.add_parsed(ev).unwrap();
        }
        // Align slot_time to header.at - 1000ms so header_delta is 1000.
        let header_at = group.block_header.as_ref().unwrap().at;
        group.slot_time = Some(header_at - chrono::Duration::milliseconds(1000));
        assert!(group.is_ok());
    }
}
