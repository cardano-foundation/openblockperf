# Backend handoff: peer relevance snapshots

**Audience:** backend agent  
**Client:** openblockperf A1 (sliding 30‑minute relevance)

## Status

The client **collects** and **journals** `peerRelevanceSnapshot` every 30 minutes.
It does **not** POST to the API yet. Please add an ingest endpoint; the client
will wire `POST` in a follow-up.

## Semantics

* Fixed **sliding 30 minutes** of local observations (not configurable).
* Per remote IP (IPv4/IPv6 not merged):

| Field | Meaning |
|-------|---------|
| `headers_1st_count` | times this IP was 1st header announcer |
| `headers_2nd_count` | 2nd announcer |
| `headers_3rd_count` | 3rd announcer |
| `headers_count` | sum of the three |
| `header_points` | `10*1st + 5*2nd + 3*3rd` |
| `bodies_count` | times this IP was first body server |
| `body_points` | `10 * bodies_count` |

Blocksample submit to the existing API is unchanged (still first header / first body only).

## Example journal / future POST body

```json
{
  "kind": "peerRelevanceSnapshot",
  "at": "2026-09-16T15:00:00+00:00",
  "window_seconds": 1800,
  "peers": [
    {
      "remote_addr": "203.0.113.10",
      "headers_count": 4,
      "headers_1st_count": 2,
      "headers_2nd_count": 1,
      "headers_3rd_count": 1,
      "header_points": 28,
      "bodies_count": 1,
      "body_points": 10
    }
  ]
}
```

Suggested route: `POST /submit/peerrelevance` (name TBD) with API key auth like other submits.
Empty `peers` arrays are possible after quiet periods; accepting them is fine.
