# OpenBlockPerf Trace Options

This guide describes recommended trace options for a Cardano relay node, 
specifically by adding traces for collecting data from openBlockperf block 
samples.

Please note that the following is absolutely necessary

- Stdout MachineFormat
- BlockFetch.Client
  - DownloadedHeader
  - SendFetchRequest
  - CompletedBlockFetch
- ChainDB.AddBlockEvent
  - AddedToCurrentChain
  - SwitchedToAFork
- Net.ConnectionManager.Remote (Info, no parent maxFrequency)
- Net.PeerSelection (Info)
- Net.InboundGovernor.Remote (Info)
- Net.Server (Info) so we see Started/Stopped for node epochs

Throttle only `Net.ConnectionManager.Remote.ConnectionManagerCounters`.
Do not enable `Net.InboundGovernor.Local` promote/demote. That is n2c / unix,
not outbound n2n.

This traceOptions are optimized for a relay node. 

## Log transport modes

OpenBlockperf supports two ingestion modes:

- journald mode (default): cardano-node writes tracer JSON to stdout and systemd/journald is used as source. Config `node_unit_name` is the systemd unit passed to `journalctl --unit`.
- logfile mode (optional): set `tracer_log_file` in the blockperf config to the active JSON logfile path (cardano-tracer or node file backend). Openblockperf follows that path across log rotation.

### Logfile mode and `node_unit_name`

In logfile mode, `node_unit_name` is a **content filter**, not the systemd unit name:

- Prefer the JSON `host` field from a sample log line (for example `"host":"hh-hongkong"`).
- Or set `node_unit_name` to `""` to accept all lines (typical for a dedicated single-node logfile).
- Do not leave a systemd unit such as `cnode.service` as the filter unless that string appears in each log line. The reader will otherwise skip every message.

Example config keys:

```json
"tracer_log_file": "/opt/cardano/cnode/logs/cnode/node.json",
"node_unit_name": "hh-hongkong"
```

See also [Installer Guide](blockperf-install.md#switching-an-existing-install-to-logfile-mode) for switching an existing deployment.

## Recommended TraceOptions

```json
  "TraceOptions": {
    "": {
      "backends": [
        "Stdout MachineFormat",
        "PrometheusSimple 127.0.0.1 12798"
      ],
      "severity": "Notice"
    },
    "Version.NodeVersion": {
      "severity": "Info"
    },
    "Startup.DiffusionInit": {
      "severity": "Info"
    },
    "Resources": {
      "severity": "Info",
      "maxFrequency": 0.0167
    },
    "ChainSync.Client.DownloadedHeader": {
      "severity": "Info",
      "maxFrequency": 14.0
    },
    "BlockFetch.Client.SendFetchRequest": {
      "severity": "Info"
    },
    "BlockFetch.Client.CompletedBlockFetch": {
      "severity": "Info",
      "maxFrequency": 4.0
    },
    "ChainDB.LedgerEvent.Replay": {
      "severity": "Info",
      "maxFrequency": 0.0668
    },
    "ChainDB.ImmDbEvent": {
      "severity": "Warning"
    },
    "ChainDB.ImmDbEvent.ChunkValidation.ValidatedChunk": {
      "severity": "Info"
    },
    "ChainDB.AddBlockEvent.AddedToCurrentChain": {
      "severity": "Info"
    },
    "ChainDB.AddBlockEvent.SwitchedToAFork": {
      "severity": "Info"
    },
    "Net.ConnectionManager.Remote": {
      "severity": "Info"
    },
    "Net.ConnectionManager.Remote.ConnectionManagerCounters": {
      "severity": "Info",
      "maxFrequency": 0.0167
    },
    "Net.ConnectionManager.Remote.ConnectionHandler.HandshakeSuccess": {
      "severity": "Info"
    },
    "Net.PeerSelection": {
      "severity": "Info"
    },
    "Net.Server": {
      "severity": "Info"
    },
    "Net.InboundGovernor.Remote": {
      "severity": "Info"
    },
    "Net.InboundGovernor.Remote.InboundGovernorCounters": {
      "severity": "Info",
      "maxFrequency": 0.0167
    },
    "Net.AcceptPolicy.ConnectionRateLimiting": {
      "severity": "Info",
      "maxFrequency": 0.0167
    },
    "Net.AcceptPolicy.ConnectionLimitResume": {
      "severity": "Info",
	  "maxFrequency": 0.0167
    }
  }
}
```

For the full, detailed traceOptions reference, see:

- [Tracer options reference](tracerOptions.md)

you can generate this reference with specific notes related to your own node config with this command

```shell
cardano-node trace-documentation --config config.json --output-file tracerOptions.md
```

Parsed tracer events are submitted to OpenBlockPerf API edges discovered via
DNS SRV (see [OpenBlockPerf Client Overview](blockperf-client.md)).


