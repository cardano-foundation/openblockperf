//! Long-running service orchestration (TaskGroup equivalent).

use crate::apiclient::ApiClient;
use crate::blocksample::BlockSampleGroup;
use crate::config::AppSettings;
use crate::events::{parse_event, EventError, ParsedEvent};
use crate::ip_obfuscate::obfuscate_addr;
use crate::logreader::{make_log_reader, NodeLogReader};
use crate::peer_tracker::PeerTracker;
use anyhow::Result;
use futures::StreamExt;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{Mutex, RwLock};
use tokio::time::{interval, Duration};
use tracing::{info, warn};

pub const CLIENT_VERSION: &str = env!("CARGO_PKG_VERSION");

pub struct Blockperf {
    settings: AppSettings,
}

impl Blockperf {
    pub fn new(settings: AppSettings) -> Self {
        Self { settings }
    }

    /// Run the service until cancelled or a task fails.
    pub async fn start(self) -> Result<()> {
        let settings = Arc::new(self.settings);
        let api = Arc::new(Mutex::new(
            ApiClient::new((*settings).clone(), true).await?,
        ));
        let tracker = Arc::new(Mutex::new(PeerTracker::new(
            HashMap::new(),
            settings.peer_event_stable_seconds,
            settings.peer_signal_ttl_seconds,
        )));
        let groups: Arc<Mutex<HashMap<String, BlockSampleGroup>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let synced = Arc::new(RwLock::new(true));
        let pending_reports: Arc<Mutex<Vec<crate::peer_tracker::PeerReport>>> =
            Arc::new(Mutex::new(Vec::new()));

        let mut set = tokio::task::JoinSet::new();

        {
            let api = api.clone();
            set.spawn(async move {
                let mut guard = api.lock().await;
                let _ = guard
                    .submit_clientinfo("unknown", CLIENT_VERSION)
                    .await;
                Ok::<(), anyhow::Error>(())
            });
        }

        {
            let settings = settings.clone();
            let tracker = tracker.clone();
            let groups = groups.clone();
            let synced = synced.clone();
            let pending_reports = pending_reports.clone();
            set.spawn(async move {
                process_events(settings, tracker, groups, synced, pending_reports).await
            });
        }

        {
            let settings = settings.clone();
            let groups = groups.clone();
            let api = api.clone();
            set.spawn(async move { send_block_samples(settings, groups, api).await });
        }

        {
            let tracker = tracker.clone();
            let api = api.clone();
            let pending_reports = pending_reports.clone();
            set.spawn(async move { flush_peer_reports(tracker, api, pending_reports).await });
        }

        {
            let api = api.clone();
            set.spawn(async move { refresh_api_endpoints(api).await });
        }

        {
            let tracker = tracker.clone();
            set.spawn(async move { peer_stats_loop(tracker).await });
        }

        while let Some(joined) = set.join_next().await {
            match joined {
                Ok(Ok(())) => {
                    warn!("a service task exited cleanly; shutting down");
                    set.abort_all();
                    break;
                }
                Ok(Err(e)) => {
                    set.abort_all();
                    return Err(e);
                }
                Err(e) => {
                    set.abort_all();
                    return Err(e.into());
                }
            }
        }
        Ok(())
    }
}

async fn process_events(
    settings: Arc<AppSettings>,
    tracker: Arc<Mutex<PeerTracker>>,
    groups: Arc<Mutex<HashMap<String, BlockSampleGroup>>>,
    synced: Arc<RwLock<bool>>,
    pending_reports: Arc<Mutex<Vec<crate::peer_tracker::PeerReport>>>,
) -> Result<()> {
    let mut reader: Box<dyn NodeLogReader> = make_log_reader(
        settings.tracer_log_file.as_deref(),
        &settings.node_unit_name,
    );
    reader.connect().await?;
    info!("log reader connected");
    let mut stream = reader.read_messages();
    while let Some(item) = stream.next().await {
        let raw = item?;
        if !*synced.read().await {
            continue;
        }
        let parsed = match parse_event(&raw) {
            Ok(p) => p,
            Err(EventError::UnknownNamespace(_)) => continue,
            Err(e) => {
                warn!(error = %e, "invalid event");
                continue;
            }
        };
        match parsed {
            ParsedEvent::DownloadedHeader(ref e) => {
                let hash = e.block_hash.clone();
                let mut groups = groups.lock().await;
                let group = groups
                    .entry(hash.clone())
                    .or_insert_with(|| BlockSampleGroup::new(hash, (*settings).clone()));
                let _ = group.add_parsed(ParsedEvent::DownloadedHeader(e.clone()));
                let mut t = tracker.lock().await;
                let _ = t.touch_signal_addr(&e.endpoints.remote_addr, e.at);
            }
            ParsedEvent::SendFetchRequest(ref e) => {
                let hash = e.block_hash.clone();
                let mut groups = groups.lock().await;
                let group = groups
                    .entry(hash.clone())
                    .or_insert_with(|| BlockSampleGroup::new(hash, (*settings).clone()));
                let _ = group.add_parsed(ParsedEvent::SendFetchRequest(e.clone()));
            }
            ParsedEvent::CompletedBlockFetch(ref e) => {
                let hash = e.block_hash.clone();
                let mut groups = groups.lock().await;
                if let Some(group) = groups.get_mut(&hash) {
                    let _ = group.add_parsed(ParsedEvent::CompletedBlockFetch(e.clone()));
                }
                let mut t = tracker.lock().await;
                let _ = t.touch_signal_addr(&e.endpoints.remote_addr, e.at);
            }
            ParsedEvent::ChainAdopt(ref e) => {
                let hash = e.block_hash.clone();
                let mut groups = groups.lock().await;
                if let Some(group) = groups.get_mut(&hash) {
                    let _ = group.add_parsed(ParsedEvent::ChainAdopt(e.clone()));
                }
            }
            ParsedEvent::HandshakeSuccess(ref h) => {
                let reports = {
                    let mut t = tracker.lock().await;
                    t.open_handshake(
                        &h.endpoints.local_addr,
                        h.endpoints.local_port,
                        &h.endpoints.remote_addr,
                        h.endpoints.remote_port,
                        h.n2n_version,
                        h.diffusion_mode.clone(),
                        h.peer_sharing.clone(),
                        h.peras_support.clone(),
                        h.at,
                        &h.ns,
                    )
                };
                pending_reports.lock().await.extend(reports);
            }
            ParsedEvent::Peer(ref p) => {
                let reports = {
                    let mut t = tracker.lock().await;
                    t.apply_event(p)
                };
                pending_reports.lock().await.extend(reports);
            }
            ParsedEvent::NetworkLifecycle(ref n) => {
                let reports = {
                    let mut t = tracker.lock().await;
                    if n.start {
                        t.on_network_start(n.at, &n.ns)
                    } else {
                        t.on_network_stop(n.at, &n.ns)
                    }
                };
                pending_reports.lock().await.extend(reports);
            }
            ParsedEvent::Ignored => {}
        }
    }
    drop(stream);
    reader.close().await?;
    Ok(())
}

async fn send_block_samples(
    settings: Arc<AppSettings>,
    groups: Arc<Mutex<HashMap<String, BlockSampleGroup>>>,
    api: Arc<Mutex<ApiClient>>,
) -> Result<()> {
    let mut tick = interval(Duration::from_secs(settings.block_sample_check_interval.max(1)));
    loop {
        tick.tick().await;
        let mut ready = Vec::new();
        {
            let mut groups = groups.lock().await;
            let keys: Vec<_> = groups.keys().cloned().collect();
            for key in keys {
                let Some(group) = groups.get(&key) else {
                    continue;
                };
                if group.age_seconds() < settings.min_age {
                    continue;
                }
                if group.is_complete() && group.is_ok() {
                    if let Some(mut sample) = group.get_sample() {
                        sample.header_remote_addr =
                            obfuscate_addr(&sample.header_remote_addr, &settings.obfuscate_ips);
                        sample.block_remote_addr =
                            obfuscate_addr(&sample.block_remote_addr, &settings.obfuscate_ips);
                        sample.local_addr =
                            obfuscate_addr(&sample.local_addr, &settings.obfuscate_ips);
                        ready.push((key, sample));
                    }
                } else if group.age_seconds() > 600 {
                    groups.remove(&key);
                }
            }
            for (key, _) in &ready {
                groups.remove(key);
            }
        }
        for (_, sample) in ready {
            let mut api = api.lock().await;
            if let Err(e) = api.submit_blocksample(&sample).await {
                warn!(error = %e, "submit blocksample failed");
            }
        }
    }
}

async fn flush_peer_reports(
    tracker: Arc<Mutex<PeerTracker>>,
    api: Arc<Mutex<ApiClient>>,
    pending_reports: Arc<Mutex<Vec<crate::peer_tracker::PeerReport>>>,
) -> Result<()> {
    let mut tick = interval(Duration::from_secs(5));
    loop {
        tick.tick().await;
        let mut batch = {
            let mut pending = pending_reports.lock().await;
            std::mem::take(&mut *pending)
        };
        {
            let mut t = tracker.lock().await;
            let now = chrono::Utc::now();
            batch.extend(t.expire_stale(now));
        }
        let mut api = api.lock().await;
        for report in batch {
            if let Err(e) = api.submit_peer_report(&report).await {
                warn!(error = %e, "submit peerevent failed");
            }
        }
    }
}

async fn refresh_api_endpoints(api: Arc<Mutex<ApiClient>>) -> Result<()> {
    let mut tick = interval(Duration::from_secs(3600));
    loop {
        tick.tick().await;
        let mut api = api.lock().await;
        if let Err(e) = api.refresh_endpoints().await {
            warn!(error = %e, "endpoint refresh failed");
        }
    }
}

async fn peer_stats_loop(tracker: Arc<Mutex<PeerTracker>>) -> Result<()> {
    let mut tick = interval(Duration::from_secs(30));
    loop {
        tick.tick().await;
        let t = tracker.lock().await;
        info!(
            open = t.open_count(),
            useful = t.useful_count(),
            generation = t.node_generation,
            "peer tracker"
        );
    }
}
