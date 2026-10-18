# Rust client parity (explore-first)

**Status:** experimental spike in [`rust/`](../rust/). Python remains the
production client until the parity gate below is green and we decide
replace vs dual.

**Decisions (2026-10-18)**

1. Rust lives in this same repository under `rust/` (polyglot), not a new repo.
2. Python is source of truth for behavior until the parity gate passes.
3. Shared golden JSON under [`testdata/`](../testdata/) is the sync surface
   for both pytest and `cargo test`.
4. During explore phase, Python PRs that change parser/FSM/API shape should
   update `testdata/` and tick the checklist here; Rust need not land in the
   same PR.
5. Installers stay Python/venv until a binary is SPO-tested.

## Hot modules (port risk order)

| Module | Python | Rust |
|--------|--------|------|
| Peer session FSM | `src/openblockperf/peer_tracker.py` | `rust/src/peer_tracker.rs` |
| Event models | `src/openblockperf/models/events.py` | `rust/src/events.rs` |
| Blocksample groups | `src/openblockperf/blocksamplegroup.py` | `rust/src/blocksample.rs` |
| Log readers | `src/openblockperf/logreader.py` | `rust/src/logreader.rs` |
| Discovery | `src/openblockperf/discovery.py` | `rust/src/discovery.rs` |
| API client | `src/openblockperf/apiclient/` | `rust/src/apiclient.rs` |
| Registration / calidus | `calidus.py`, `commands/register_*` | `rust/src/calidus.rs`, CLI |

## Parity checklist

### Fixture / unit (in-repo)

- [x] ConnectionId IPv4/IPv6 parse
- [x] Core blocksample event parse (header / fetch / complete / adopt)
- [x] BlockSampleGroup `is_complete` / `is_ok` / `get_sample` against conftest chain
- [x] PeerTracker open / temperature / close / restart paths against golden events
- [x] Discovery URL helpers + override base URL
- [x] API payload shapes (BlockSample, PeerEventRequest)

### Staging / relay (manual gate)

These need a real relay and staging API access. Not runnable from CI alone.

- [ ] Haskell node ingest on a real relay (journald or tracer file)
- [ ] Amaru node ingest on a real relay
- [ ] `register-ip` against staging (Python until Rust grows the command)
- [ ] `register-calidus` against staging (`rust` binary: `blockperf register-calidus`)
- [ ] Discovery SRV failover smoke
- [ ] Side-by-side payload compare (Python vs Rust) for same log window

**Gate status (2026-10-18):** in-repo unit/fixture parity for the spike is green
(`cd rust && cargo test`). Staging/relay items above are still open. Until they
pass, keep shipping Python; do not switch installers.

### Decision after gate

- [ ] Choose **replace** (Rust production, Python reference then deprecate)
      or **dual** (fixture updates required in the same PR for both)

Default until then: **explore-first** (this doc's status).

## Agent / workspace notes

One Cursor workspace on this repo is enough: Python, Rust, docs, and
`testdata/` share context. Prefer one chat for cross-language parity work;
split chats only for large parallel tracks, still pointing at the same
workspace and this doc.

## Build

```bash
cd rust
cargo test
cargo build --release
```

Binary name: `blockperf` (same CLI surface as Python where implemented).
