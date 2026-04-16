# OpenBlockPerf Client Overview

The OpenBlockPerf client is published on PyPI as `[openblockperf](https://pypi.org/project/openblockperf/)`.

In most cases, the client is installed and configured with the
[Installer Guide](blockperf-install.md) and runs afterwards as a systemd
service on a Cardano relay node.

Once installed and started, the OpenBlockPerf client parses selected namespace
tracer messages emitted by `cardano-node`. This is why a specific set of node
tracers must be enabled in the node configuration. See the
[Trace Options Guide](blockperf-traceoptions.md).

The parsed information is submitted to a central backend endpoint with the goal
of building a common global view of Cardano blockchain network behavior and of
block and transaction propagation flows, while avoiding exposure of security
relevant information.

OpenBlockPerf is intended to run on relay nodes, which act as the gateway
between a stake pool's producer node and the rest of the global Cardano
network. The client can also run on producer nodes, but this is not
recommended.

## What the client reports

The client is mainly interested in three categories of telemetry.

## 1. Block propagation times

Each block is minted somewhere in the world and then distributed through a
decentralized peer-to-peer network. This propagation takes time. Ouroboros
assumes and expects blocks to propagate globally within about 1 second to avoid
height races (battles), or at least within 3-5 slots (seconds).

OpenBlockPerf does not only look at the final time until a newly somehwere around 
the globe minted block is adopted locally. Instead, it observes four 
fundamental stages and measures them in millisecond detail.

1. Time until a relay node first hears about the new block header.
2. Time while the relay node requests the block body from peers.
3. Time until the block body download completes.
4. Time until the local node validates and adopts the block.

These four stages reflect different infrastructure and resource properties such
as geographical distance, latency, network speed, block size, peering topology,
and local compute and I/O capacity.

For each observed block, these four timespans form a `blocksample`, which is
submitted to the OpenBlockPerf backend. Different relay nodes at different
geographic locations, with different network connections and hardware profiles,
report blocksamples for the same block. Combined, this creates valuable data
for research, engineering, protocol tuning, and protocol evolution. It can also
support governance analysis when proposals may affect network behavior.

## 2. Network peering topology

Each relay node aims to maintain a useful set of inbound and outbound peer
connections. To put blocksamples into the right context and better understand
the dynamic global network over time and under changing conditions, the
OpenBlockPerf client also tracks and submits newly active and disappeared remote
peer connections.

This helps relate propagation behavior to the actual peer topology seen by
participating relay nodes.

## 3. Relay node version and context information

To better understand under which conditions blocksamples and peering events were
collected, the client also reports contextual metadata such as:

- cardano-node version
- relay IP and port
- OpenBlockPerf client version

This context is useful for statistical reporting over time and for operational
analysis, for example when evaluating hard fork readiness or identifying
unexpected network behavior between specific node versions or network segments.

## Why OpenBlockPerf?

The shared dataset can support research, engineering, hard fork preparation,
governance analysis, and higher-level applications. The collected data is meant
to be generally available rather than kept private, while still being shared in
a security-aware and anonymized form.

Participating stake pool operators also benefit directly. They gain insights
into how the broader network perceived blocks minted by their pool and how
their relay connectivity behaved from the outside. This complements the
operator's own internal monitoring and can improve infrastructure awareness and
operational decision making.