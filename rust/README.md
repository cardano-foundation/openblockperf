# OpenBlockperf (Rust explore)

Experimental Rust port of the Python client. **Python remains production**
until the gate in [`docs/rust-parity.md`](../docs/rust-parity.md) passes.

## Build / test

```bash
cd rust
cargo test
cargo build --release
./target/release/blockperf version
```

Shared golden JSON lives in [`../testdata/`](../testdata/).

## CLI (spike surface)

| Command | Status |
|---------|--------|
| `blockperf version` | implemented |
| `blockperf run` | implemented (journalctl / file tail, submit loops) |
| `blockperf register-calidus` | implemented |
| `blockperf register-ip` | not yet (use Python) |

Config: `--config` / `OPENBLOCKPERF_CONFIG` JSON with the usual keys
(`api_url`, `api_key`, `network`, `node_unit_name`, `tracer_log_file`, …).
