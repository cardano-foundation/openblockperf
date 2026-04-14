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
- Net.ConnectionManager.Remote

The remaining traceOptions are optimized for a relay node. 

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
    "Net.PeerSelection": {
      "severity": "Info"
    },
    "Net.InboundGovernor.Remote": {
      "severity": "Info"
    },
    "Net.InboundGovernor.Local.InboundGovernorCounters": {
      "severity": "Info",
      "maxFrequency": 0.0167
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

