# Backend handoff: peer relevance snapshots (CANCELLED)

**Status:** cancelled **2026-09-17**.

We will **not** add `POST /submit/peerrelevance` or a dedicated relevance
table.

## Why cancelled

1. Aggregated snapshots need a new backend table and endpoint.
2. 1st header / 1st body are already in blocksamples; the useful extra
   signal is 2nd / 3rd announcer, which we can put on the sample itself.
3. Precomputed scores are easier for an operator to fake than per-block
   announcer fields derived from node log events.

## Replacement

See **`docs/backend-blocksample.md`**: extend `POST /submit/blocksample`
with `header2_*` / `header3_*`, then two more relay lookups on
`block_prop`.

Client still computes sliding 30m relevance for **local metrics only**
(`docs/local-peer-metrics.md`). That data is not submitted.
