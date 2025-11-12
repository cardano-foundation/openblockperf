# New Tracer system

## General Setup

### Configure the node

The node needs to be configured to use the new tracing system. This is done
by:

* Providing `UseTraceDispatcher: true` in the node config.json
* Providing the socket of the tracer in the startup options
* Having A tracer configuration in the nodes config.json for the tracer
    to pick up and know what and where to trace logs to.

The cardano-node binary takes two options for the tracer socket path:
`--tracer-socket-path-accept FILEPATH` and `--tracer-socket-path-connect FILEPATH`.
Both take a file path to a socket file. The difference is that one tells
the node to accept connects from a cardano-tracer instance while the other
tells the node to connect to an existing cardano-tracer instance both
through the given socket path.

I chose to have the node accept connects from tracer instance which means
that the node will create the socket file! The cardano-tracer service
will the connect to that socket and receive logs.

## Node TracerOptions

Once enabled the node will need to receive the configuration for the
tracer system. That is provided through the `TracerOptions` block.

A simple example might look like this:

```json
"TraceOptions": {
    "": {
        "severity": "Notice",
        "detail": "DNormal",
        "backends": [
          "Stdout MachineFormat",
          "EKGBackend",
          "Forwarder"
        ]
    },
    "ChainDB": {
        "severity": "Info",
        "detail": "DDetailed"
    },
    "ChainDB.AddBlockEvent.AddedBlockToQueue": {
        "maxFrequency": 2.0
    }
}
```

Read this to get into the details of how to configure the tracers behaviour
in the [developer portal](https://developers.cardano.org/docs/operate-a-stake-pool/node-operations/new-tracing-system/new-tracing-system/#node-side-configuration-of-new-tracing).


## The cardano-tracer service

The cardano-tracer is running as a seperate service on the same machine. So
you will want to create a service unit and a configuration file for that.

A service Unit could look like this:

```ini
[Unit]
Description=Cardano Tracer
After=syslog.target network.target

[Service]
Type=simple
User=cardano-node
Group=cardano-node
Restart=always
RestartSec=10
ExecStart=/usr/local/bin/cardano-tracer --config /etc/cardano-tracer.config
SyslogIdentifier=cardano-tracer

[Install]
WantedBy=multi-user.target
```

As you can see it only receives the config file which will configure the
tracer itself. Here is how a config file would look:

```yaml
networkMagic: 764824073
network:
  tag: ConnectTo
  contents: [
    "/opt/cardano-node/db/tracer.socket"
  ]
logging:
  - logRoot: "/tmp/cardano-tracer-logs-json"
    logMode: FileMode
    logFormat: ForMachine
  - logRoot: "/tmp/cardano-tracer-logs-text"
    logMode: JournalMode
    logFormat: ForMachine
```

### ConnecTo AcceptAt

As mentioned before the tracer can either connect to the node or
receive connections from the node. While `AcceptAt` takes a single
string in `contents` which is the path to the socket it accepts connections
at, the `ConnectTo` actually expects `contents` to be a list of strings.
These strings are the socket paths it should connect to.

