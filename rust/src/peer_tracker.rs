//! Connection-session tracking (port of Python peer_tracker.py).

use crate::events::{PeerEvent, PeerEventChangeType};
use crate::peer::{
    connection_key, submit_port, CloseReason, EventRole, PeerDirection, PeerState,
};
use chrono::{DateTime, Duration, Utc};
use std::collections::HashMap;
use uuid::Uuid;

const GENERATION_DEBOUNCE_SECS: i64 = 2;

#[derive(Debug, Clone)]
pub struct Peer {
    pub ns: Option<String>,
    pub local_addr: String,
    pub local_port: i32,
    pub remote_addr: String,
    pub remote_port: i32,
    pub state_inbound: PeerState,
    pub state_outbound: PeerState,
    pub duplex: bool,
    pub n2n_version: Option<i32>,
    pub diffusion_mode: Option<String>,
    pub peer_sharing: Option<String>,
    pub peras_support: Option<String>,
    pub first_seen: Option<DateTime<Utc>>,
    pub last_signal: Option<DateTime<Utc>>,
    pub last_updated: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct PeerSession {
    pub node_generation: u64,
    pub session_id: String,
    pub local_addr: String,
    pub local_port: i32,
    pub remote_addr: String,
    pub remote_port: i32,
    pub opened_at: DateTime<Utc>,
    pub last_ns: Option<String>,
    pub we_dialed: Option<bool>,
    pub n2n_version: Option<i32>,
    pub diffusion_mode: Option<String>,
    pub peer_sharing: Option<String>,
    pub peras_support: Option<String>,
    pub ig_temperature: PeerState,
    pub outbound_temperature: PeerState,
    pub useful: bool,
    pub warm_since: Option<DateTime<Utc>>,
    pub last_signal: Option<DateTime<Utc>>,
    pub closed_at: Option<DateTime<Utc>>,
    pub close_reason: Option<CloseReason>,
    pub opened_submitted: bool,
    pub ig_submitted: Option<PeerState>,
    pub out_submitted: Option<PeerState>,
}

impl PeerSession {
    fn conn_key(&self) -> String {
        connection_key(
            &self.local_addr,
            self.local_port,
            &self.remote_addr,
            self.remote_port,
        )
    }

    fn is_open(&self) -> bool {
        self.closed_at.is_none()
    }

    fn as_peer(&self) -> Peer {
        Peer {
            ns: self.last_ns.clone(),
            local_addr: self.local_addr.clone(),
            local_port: self.local_port,
            remote_addr: self.remote_addr.clone(),
            remote_port: submit_port(self.remote_port),
            state_inbound: self.ig_temperature,
            state_outbound: self.outbound_temperature,
            duplex: false,
            n2n_version: self.n2n_version,
            diffusion_mode: self.diffusion_mode.clone(),
            peer_sharing: self.peer_sharing.clone(),
            peras_support: self.peras_support.clone(),
            first_seen: Some(self.opened_at),
            last_signal: Some(self.last_signal.unwrap_or(self.opened_at)),
            last_updated: self.last_signal.unwrap_or(self.opened_at),
        }
    }
}

#[derive(Debug, Clone)]
pub struct PeerReport {
    pub peer: Peer,
    pub direction: PeerDirection,
    pub change_type: PeerEventChangeType,
    pub state: String,
    pub at: DateTime<Utc>,
    pub remote_port: i32,
    pub event_role: EventRole,
    pub node_generation: u64,
    pub session_id: Option<String>,
    pub close_reason: Option<CloseReason>,
    pub we_dialed: Option<bool>,
}

fn is_active(state: PeerState) -> bool {
    matches!(state, PeerState::Warm | PeerState::Hot)
}

pub struct PeerTracker {
    pub peers: HashMap<String, Peer>,
    stable_seconds: u64,
    signal_ttl_seconds: u64,
    pub node_generation: u64,
    open: HashMap<String, PeerSession>,
    closed: HashMap<String, PeerSession>,
    opened_count: u64,
    close_counts: HashMap<&'static str, u64>,
    last_generation_at: Option<DateTime<Utc>>,
    #[allow(dead_code)]
    stopped: bool,
}

impl PeerTracker {
    pub fn new(
        peers: HashMap<String, Peer>,
        stable_seconds: u64,
        signal_ttl_seconds: u64,
    ) -> Self {
        Self {
            peers,
            stable_seconds,
            signal_ttl_seconds,
            node_generation: 0,
            open: HashMap::new(),
            closed: HashMap::new(),
            opened_count: 0,
            close_counts: HashMap::new(),
            last_generation_at: None,
            stopped: false,
        }
    }

    pub fn open_handshake(
        &mut self,
        local_addr: &str,
        local_port: i32,
        remote_addr: &str,
        remote_port: i32,
        n2n_version: Option<i32>,
        diffusion_mode: Option<String>,
        peer_sharing: Option<String>,
        peras_support: Option<String>,
        at: DateTime<Utc>,
        ns: &str,
    ) -> Vec<PeerReport> {
        if let Some(existing) = self.find_open(local_addr, local_port, remote_addr, remote_port) {
            let key = existing.conn_key();
            self.rekey_local(&key, local_addr, local_port);
            let lookup = connection_key(local_addr, local_port, remote_addr, remote_port);
            let session_key = if self.open.contains_key(&lookup) {
                Some(lookup)
            } else {
                self.open
                    .iter()
                    .find(|(_, s)| s.remote_addr == remote_addr && s.remote_port == remote_port)
                    .map(|(k, _)| k.clone())
            };
            if let Some(sk) = session_key {
                if let Some(session) = self.open.get_mut(&sk) {
                    session.n2n_version = n2n_version;
                    session.diffusion_mode = diffusion_mode;
                    session.peer_sharing = peer_sharing;
                    session.peras_support = peras_support;
                    session.last_ns = Some(ns.to_string());
                    Self::touch_session(session, at);
                    let snap = session.clone();
                    self.sync_ip_peer(&snap);
                }
            }
            return vec![];
        }

        let mut session = self.new_session(local_addr, local_port, remote_addr, remote_port, at, Some(ns));
        session.n2n_version = n2n_version;
        session.diffusion_mode = diffusion_mode;
        session.peer_sharing = peer_sharing;
        session.peras_support = peras_support;
        Self::touch_session(&mut session, at);
        self.maybe_mark_useful(&mut session, at);
        let report = self.open_report(&mut session, at);
        let key = session.conn_key();
        self.opened_count += 1;
        self.sync_ip_peer(&session);
        self.open.insert(key, session);
        vec![report]
    }

    pub fn apply_event(&mut self, event: &PeerEvent) -> Vec<PeerReport> {
        let at = event.at;
        let new_state = event.state;
        let is_close = Self::is_close_event(event, new_state);
        let existing = self.find_open(
            &event.endpoints.local_addr,
            event.endpoints.local_port,
            &event.endpoints.remote_addr,
            event.endpoints.remote_port,
        );
        if existing.is_none() && is_close {
            return vec![];
        }
        let mut session = self.session_for_event(event, at);
        session.last_ns = Some(event.ns.clone());
        Self::touch_session(&mut session, at);

        let mut reports = Vec::new();
        if !session.opened_submitted {
            let opened_at = session.opened_at;
            reports.push(self.open_report(&mut session, opened_at));
        }
        if event.direction == PeerDirection::Outbound {
            reports.extend(self.apply_outbound(&mut session, new_state, event, at));
        } else {
            reports.extend(self.apply_inbound(&mut session, new_state, event, at));
        }
        if session.is_open() {
            self.maybe_mark_useful(&mut session, at);
            self.sync_ip_peer(&session);
            let key = session.conn_key();
            self.open.insert(key, session);
        }
        reports
    }

    pub fn expire_stale(&mut self, now: DateTime<Utc>) -> Vec<PeerReport> {
        if self.signal_ttl_seconds == 0 {
            return vec![];
        }
        let ttl = Duration::seconds(self.signal_ttl_seconds as i64);
        let mut reports = Vec::new();
        let keys: Vec<_> = self.open.keys().cloned().collect();
        for key in keys {
            let Some(session) = self.open.get(&key).cloned() else {
                continue;
            };
            let last = session.last_signal.unwrap_or(session.opened_at);
            if now - last < ttl {
                continue;
            }
            let mut session = session;
            reports.extend(self.close_session(&mut session, now, CloseReason::Ttl));
        }
        reports
    }

    pub fn on_network_stop(&mut self, at: DateTime<Utc>, ns: &str) -> Vec<PeerReport> {
        self.stopped = true;
        let mut reports = Vec::new();
        let sessions: Vec<_> = self.open.values().cloned().collect();
        for mut session in sessions {
            if !ns.is_empty() {
                session.last_ns = Some(ns.to_string());
            }
            reports.extend(self.close_session(&mut session, at, CloseReason::NodeRestart));
        }
        reports
    }

    pub fn on_network_start(&mut self, at: DateTime<Utc>, ns: &str) -> Vec<PeerReport> {
        if let Some(last) = self.last_generation_at {
            if at - last < Duration::seconds(GENERATION_DEBOUNCE_SECS) {
                return vec![];
            }
        }
        let mut reports = Vec::new();
        if !self.open.is_empty() {
            reports.extend(self.on_network_stop(at, ns));
        }
        self.node_generation += 1;
        self.last_generation_at = Some(at);
        self.stopped = false;
        reports.push(self.node_restart_report(at, ns));
        reports
    }

    pub fn open_count(&self) -> usize {
        self.open.len()
    }

    pub fn useful_count(&self) -> usize {
        self.open.values().filter(|s| s.useful).count()
    }

    /// Refresh last_signal on open sessions for this IP (header/body).
    pub fn touch_signal_addr(&mut self, remote_addr: &str, at: DateTime<Utc>) -> bool {
        let mut hit = false;
        for session in self.open.values_mut() {
            if session.remote_addr != remote_addr {
                continue;
            }
            Self::touch_session(session, at);
            hit = true;
        }
        if let Some(peer) = self.peers.get_mut(remote_addr) {
            if peer.first_seen.is_none() {
                peer.first_seen = Some(at);
            }
            peer.last_signal = Some(at);
            peer.last_updated = at;
            hit = true;
        }
        hit
    }

    fn new_session(
        &self,
        local_addr: &str,
        local_port: i32,
        remote_addr: &str,
        remote_port: i32,
        at: DateTime<Utc>,
        ns: Option<&str>,
    ) -> PeerSession {
        PeerSession {
            node_generation: self.node_generation,
            session_id: Uuid::new_v4().simple().to_string(),
            local_addr: local_addr.to_string(),
            local_port,
            remote_addr: remote_addr.to_string(),
            remote_port,
            opened_at: at,
            last_ns: ns.map(str::to_string),
            we_dialed: None,
            n2n_version: None,
            diffusion_mode: None,
            peer_sharing: None,
            peras_support: None,
            ig_temperature: PeerState::Unconnected,
            outbound_temperature: PeerState::Unconnected,
            useful: false,
            warm_since: None,
            last_signal: Some(at),
            closed_at: None,
            close_reason: None,
            opened_submitted: false,
            ig_submitted: None,
            out_submitted: None,
        }
    }

    fn find_open(
        &self,
        local_addr: &str,
        local_port: i32,
        remote_addr: &str,
        remote_port: i32,
    ) -> Option<&PeerSession> {
        let key = connection_key(local_addr, local_port, remote_addr, remote_port);
        if let Some(s) = self.open.get(&key) {
            return Some(s);
        }
        self.open
            .values()
            .find(|s| s.remote_addr == remote_addr && s.remote_port == remote_port)
    }

    fn rekey_local(&mut self, old_key: &str, local_addr: &str, local_port: i32) {
        let Some(mut session) = self.open.remove(old_key) else {
            return;
        };
        if session.local_addr == local_addr && session.local_port == local_port {
            self.open.insert(old_key.to_string(), session);
            return;
        }
        let placeholder = matches!(session.local_addr.as_str(), "0.0.0.0" | "::" | "")
            || session.local_port == 0;
        if !placeholder {
            self.open.insert(old_key.to_string(), session);
            return;
        }
        session.local_addr = local_addr.to_string();
        session.local_port = local_port;
        let key = session.conn_key();
        self.open.insert(key, session);
    }

    fn session_for_event(&mut self, event: &PeerEvent, at: DateTime<Utc>) -> PeerSession {
        if let Some(existing) = self.find_open(
            &event.endpoints.local_addr,
            event.endpoints.local_port,
            &event.endpoints.remote_addr,
            event.endpoints.remote_port,
        ) {
            let old_key = existing.conn_key();
            self.rekey_local(
                &old_key,
                &event.endpoints.local_addr,
                event.endpoints.local_port,
            );
            let key = connection_key(
                &event.endpoints.local_addr,
                event.endpoints.local_port,
                &event.endpoints.remote_addr,
                event.endpoints.remote_port,
            );
            if let Some(s) = self.open.remove(&key) {
                return s;
            }
            if let Some(s) = self
                .open
                .values()
                .find(|s| {
                    s.remote_addr == event.endpoints.remote_addr
                        && s.remote_port == event.endpoints.remote_port
                })
                .map(|s| s.conn_key())
            {
                if let Some(sess) = self.open.remove(&s) {
                    return sess;
                }
            }
        }
        let mut session = self.new_session(
            &event.endpoints.local_addr,
            event.endpoints.local_port,
            &event.endpoints.remote_addr,
            event.endpoints.remote_port,
            at,
            Some(&event.ns),
        );
        if event.ns == "Net.PeerSelection.Actions.StatusChanged"
            || event.ns.contains("PeerSelection.Selection.")
        {
            session.we_dialed = Some(true);
        }
        self.opened_count += 1;
        session
    }

    fn is_close_event(event: &PeerEvent, new_state: PeerState) -> bool {
        let ns = event.ns.as_str();
        if matches!(
            ns,
            "Net.InboundGovernor.Remote.MuxErrored"
                | "Net.InboundGovernor.Remote.ResponderErrored"
                | "Net.ConnectionManager.Remote.ConnectionHandler.Error"
                | "Net.InboundGovernor.Remote.DemotedToColdRemote"
        ) {
            return true;
        }
        if ns.contains("DemoteWarm") {
            return true;
        }
        ns == "Net.PeerSelection.Actions.StatusChanged" && new_state == PeerState::Cold
    }

    fn apply_outbound(
        &mut self,
        session: &mut PeerSession,
        new_state: PeerState,
        event: &PeerEvent,
        at: DateTime<Utc>,
    ) -> Vec<PeerReport> {
        if session.we_dialed.is_none() {
            session.we_dialed = Some(true);
        }
        let ns = event.ns.as_str();
        if ns.contains("MuxErrored")
            || ns.contains("ResponderErrored")
            || ns.contains("ConnectionHandler.Error")
        {
            let reason = Self::death_reason(ns);
            return self.close_session(session, at, reason);
        }
        if new_state == PeerState::Cooling {
            session.outbound_temperature = PeerState::Cooling;
            return vec![];
        }
        if new_state == PeerState::Cold {
            return self.close_session(session, at, CloseReason::CoolingToCold);
        }
        let old = session.outbound_temperature;
        session.outbound_temperature = new_state;
        if is_active(new_state) {
            self.temperature_report(session, PeerDirection::Outbound, old, new_state, at)
        } else {
            vec![]
        }
    }

    fn apply_inbound(
        &mut self,
        session: &mut PeerSession,
        new_state: PeerState,
        event: &PeerEvent,
        at: DateTime<Utc>,
    ) -> Vec<PeerReport> {
        let ns = event.ns.as_str();
        if ns.ends_with("MuxErrored") {
            return self.close_session(session, at, CloseReason::IgMuxError);
        }
        if ns.ends_with("ResponderErrored") {
            return self.close_session(session, at, CloseReason::IgResponderError);
        }
        if ns.ends_with("ConnectionHandler.Error") {
            return self.close_session(session, at, CloseReason::HandlerError);
        }
        if new_state == PeerState::Cold {
            if is_active(session.outbound_temperature)
                || session.outbound_temperature == PeerState::Cooling
            {
                session.ig_temperature = PeerState::Unconnected;
                session.ig_submitted = None;
                Self::touch_session(session, at);
                self.sync_ip_peer(session);
                return vec![];
            }
            return self.close_session(session, at, CloseReason::DemotedCold);
        }
        let old = session.ig_temperature;
        session.ig_temperature = new_state;
        if is_active(new_state) {
            self.temperature_report(session, PeerDirection::Inbound, old, new_state, at)
        } else {
            vec![]
        }
    }

    fn death_reason(ns: &str) -> CloseReason {
        if ns.contains("MuxErrored") {
            CloseReason::IgMuxError
        } else if ns.contains("ResponderErrored") {
            CloseReason::IgResponderError
        } else {
            CloseReason::HandlerError
        }
    }

    fn temperature_report(
        &self,
        session: &mut PeerSession,
        direction: PeerDirection,
        _old: PeerState,
        new: PeerState,
        at: DateTime<Utc>,
    ) -> Vec<PeerReport> {
        let already = if direction == PeerDirection::Inbound {
            session.ig_submitted
        } else {
            session.out_submitted
        };
        if already == Some(new) {
            return vec![];
        }
        if new == PeerState::Warm && already.is_none() {
            if direction == PeerDirection::Inbound {
                session.ig_submitted = Some(PeerState::Warm);
            } else {
                session.out_submitted = Some(PeerState::Warm);
            }
            return vec![];
        }
        let change = if new == PeerState::Warm && already == Some(PeerState::Hot) {
            PeerEventChangeType::HotWarm
        } else if new == PeerState::Hot {
            PeerEventChangeType::WarmHot
        } else if new == PeerState::Warm {
            PeerEventChangeType::ColdWarm
        } else {
            return vec![];
        };
        if direction == PeerDirection::Inbound {
            session.ig_submitted = Some(new);
        } else {
            session.out_submitted = Some(new);
        }
        vec![self.report(
            session,
            direction,
            change,
            new.as_str(),
            at,
            EventRole::Temperature,
            None,
        )]
    }

    fn open_report(&self, session: &mut PeerSession, at: DateTime<Utc>) -> PeerReport {
        session.opened_submitted = true;
        if is_active(session.ig_temperature) {
            session.ig_submitted = Some(PeerState::Warm);
        }
        if is_active(session.outbound_temperature) {
            session.out_submitted = Some(PeerState::Warm);
        }
        let direction = if session.we_dialed == Some(true) {
            PeerDirection::Outbound
        } else {
            PeerDirection::Inbound
        };
        self.report(
            session,
            direction,
            PeerEventChangeType::ColdWarm,
            PeerState::Warm.as_str(),
            at,
            EventRole::Open,
            None,
        )
    }

    fn close_session(
        &mut self,
        session: &mut PeerSession,
        at: DateTime<Utc>,
        reason: CloseReason,
    ) -> Vec<PeerReport> {
        if session.closed_at.is_some() {
            return vec![];
        }
        let key = session.conn_key();
        session.closed_at = Some(at);
        session.close_reason = Some(reason);
        session.ig_temperature = PeerState::Cold;
        session.outbound_temperature = PeerState::Cold;
        session.last_signal = Some(at);
        self.open.remove(&key);
        *self.close_counts.entry(reason.as_str()).or_insert(0) += 1;
        self.sync_ip_peer(session);
        self.closed.insert(session.session_id.clone(), session.clone());
        let mut direction = if session.we_dialed == Some(true) {
            PeerDirection::Outbound
        } else {
            PeerDirection::Inbound
        };
        if reason == CloseReason::CoolingToCold
            || (session.we_dialed == Some(true) && reason == CloseReason::NodeRestart)
        {
            direction = PeerDirection::Outbound;
        }
        vec![self.report(
            session,
            direction,
            PeerEventChangeType::WarmCold,
            PeerState::Cold.as_str(),
            at,
            EventRole::Close,
            Some(reason),
        )]
    }

    fn node_restart_report(&self, at: DateTime<Utc>, ns: &str) -> PeerReport {
        PeerReport {
            peer: Peer {
                ns: Some(if ns.is_empty() {
                    "node_restart".into()
                } else {
                    ns.into()
                }),
                local_addr: "0.0.0.0".into(),
                local_port: 0,
                remote_addr: "0.0.0.0".into(),
                remote_port: 0,
                state_inbound: PeerState::Unconnected,
                state_outbound: PeerState::Unconnected,
                duplex: false,
                n2n_version: None,
                diffusion_mode: None,
                peer_sharing: None,
                peras_support: None,
                first_seen: Some(at),
                last_signal: Some(at),
                last_updated: at,
            },
            direction: PeerDirection::Inbound,
            change_type: PeerEventChangeType::WarmCold,
            state: PeerState::Cold.as_str().into(),
            at,
            remote_port: 0,
            event_role: EventRole::NodeRestart,
            node_generation: self.node_generation,
            session_id: None,
            close_reason: Some(CloseReason::NodeRestart),
            we_dialed: None,
        }
    }

    fn report(
        &self,
        session: &PeerSession,
        direction: PeerDirection,
        change_type: PeerEventChangeType,
        state: &str,
        at: DateTime<Utc>,
        event_role: EventRole,
        close_reason: Option<CloseReason>,
    ) -> PeerReport {
        PeerReport {
            peer: session.as_peer(),
            direction,
            change_type,
            state: state.to_string(),
            at,
            remote_port: submit_port(session.remote_port),
            event_role,
            node_generation: session.node_generation,
            session_id: Some(session.session_id.clone()),
            close_reason,
            we_dialed: session.we_dialed,
        }
    }

    fn touch_session(session: &mut PeerSession, at: DateTime<Utc>) {
        session.last_signal = Some(at);
        if session.warm_since.is_none()
            && (is_active(session.ig_temperature) || is_active(session.outbound_temperature))
        {
            session.warm_since = Some(at);
        }
    }

    fn maybe_mark_useful(&self, session: &mut PeerSession, now: DateTime<Utc>) {
        if !session.is_open() || session.useful {
            return;
        }
        let ig = session.ig_temperature;
        let out = session.outbound_temperature;
        if ig == PeerState::Hot || out == PeerState::Hot {
            session.useful = true;
            return;
        }
        if !is_active(ig) && !is_active(out) {
            return;
        }
        if session.warm_since.is_none() {
            session.warm_since = Some(now);
        }
        if self.stable_seconds == 0 {
            session.useful = true;
            return;
        }
        if let Some(since) = session.warm_since {
            if now - since >= Duration::seconds(self.stable_seconds as i64) {
                session.useful = true;
            }
        }
    }

    fn sync_ip_peer(&mut self, session: &PeerSession) {
        let key = session.remote_addr.clone();
        let entry = self.peers.entry(key.clone()).or_insert_with(|| session.as_peer());
        if entry.first_seen.is_none() || session.opened_at < entry.first_seen.unwrap() {
            entry.first_seen = Some(session.opened_at);
        }
        entry.last_signal = session.last_signal.or(entry.last_signal);
        entry.last_updated = session.last_signal.unwrap_or(entry.last_updated);
        entry.ns = session.last_ns.clone();
        if session.n2n_version.is_some() {
            entry.n2n_version = session.n2n_version;
            entry.diffusion_mode = session.diffusion_mode.clone();
            entry.peer_sharing = session.peer_sharing.clone();
            entry.peras_support = session.peras_support.clone();
        }
        let sport = submit_port(session.remote_port);
        if sport != 0 && (entry.remote_port == 0 || session.we_dialed == Some(true)) {
            entry.remote_port = sport;
        }
        entry.local_addr = session.local_addr.clone();
        entry.local_port = session.local_port;

        let mut ig = PeerState::Unconnected;
        let mut out = PeerState::Unconnected;
        let mut any_open = false;
        for open_s in self.open.values() {
            if open_s.remote_addr != key {
                continue;
            }
            any_open = true;
            if open_s.ig_temperature == PeerState::Hot
                || (open_s.ig_temperature == PeerState::Warm && ig != PeerState::Hot)
            {
                ig = open_s.ig_temperature;
            }
            if open_s.outbound_temperature == PeerState::Hot
                || (open_s.outbound_temperature == PeerState::Warm && out != PeerState::Hot)
            {
                out = open_s.outbound_temperature;
            }
            if open_s.outbound_temperature == PeerState::Cooling && !is_active(out) {
                out = PeerState::Cooling;
            }
        }
        if !any_open {
            ig = PeerState::Cold;
            out = PeerState::Cold;
        }
        // Also consider the session being synced if it is still conceptually open
        // but not yet reinserted (caller may sync before insert).
        if session.is_open() && session.remote_addr == key {
            any_open = true;
            if session.ig_temperature == PeerState::Hot
                || (session.ig_temperature == PeerState::Warm && ig != PeerState::Hot)
            {
                ig = session.ig_temperature;
            }
            if session.outbound_temperature == PeerState::Hot
                || (session.outbound_temperature == PeerState::Warm && out != PeerState::Hot)
            {
                out = session.outbound_temperature;
            }
        }
        if !any_open {
            ig = PeerState::Cold;
            out = PeerState::Cold;
        }
        entry.state_inbound = ig;
        entry.state_outbound = out;
        entry.duplex = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::events::{parse_event, ParsedEvent};
    use crate::load_testdata_json;
    use crate::peer::EventRole;

    #[test]
    fn handshake_then_promote_hot_then_mux_close() {
        let mut tracker = PeerTracker::new(HashMap::new(), 0, 1800);
        let hs = load_testdata_json("events/handshake_success.json").unwrap();
        let ParsedEvent::HandshakeSuccess(h) = parse_event(&hs).unwrap() else {
            panic!("hs");
        };
        let open = tracker.open_handshake(
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
        );
        assert_eq!(open.len(), 1);
        assert_eq!(open[0].event_role, EventRole::Open);
        assert_eq!(tracker.open_count(), 1);

        let warm = load_testdata_json("events/promoted_to_warm_remote.json").unwrap();
        let ParsedEvent::Peer(w) = parse_event(&warm).unwrap() else {
            panic!("warm");
        };
        let _ = tracker.apply_event(&w);

        let hot = load_testdata_json("events/promoted_to_hot_remote.json").unwrap();
        let ParsedEvent::Peer(hh) = parse_event(&hot).unwrap() else {
            panic!("hot");
        };
        let temps = tracker.apply_event(&hh);
        assert!(temps.iter().any(|r| r.event_role == EventRole::Temperature));
        assert_eq!(tracker.useful_count(), 1);

        let mux = load_testdata_json("events/mux_errored.json").unwrap();
        let ParsedEvent::Peer(m) = parse_event(&mux).unwrap() else {
            panic!("mux");
        };
        let closed = tracker.apply_event(&m);
        assert!(closed.iter().any(|r| r.event_role == EventRole::Close));
        assert_eq!(tracker.open_count(), 0);
    }

    #[test]
    fn network_restart_bumps_generation() {
        let mut tracker = PeerTracker::new(HashMap::new(), 0, 1800);
        let start = load_testdata_json("events/server_remote_started.json").unwrap();
        let ParsedEvent::NetworkLifecycle(s) = parse_event(&start).unwrap() else {
            panic!("start");
        };
        let reports = tracker.on_network_start(s.at, &s.ns);
        assert!(reports.iter().any(|r| r.event_role == EventRole::NodeRestart));
        assert_eq!(tracker.node_generation, 1);
    }
}
