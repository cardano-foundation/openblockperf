# Shared golden fixtures

JSON (and small text) fixtures consumed by:

- Python pytest (`tests/conftest.py` loads `events/*.json`)
- Rust `cargo test` (`openblockperf::load_testdata_json`)

When a Python PR changes event parse, peer FSM, or API payload shape,
update the matching file here and note it in `docs/rust-parity.md`.
