# Events and Pydantic Models

The events that come in from the logs are implemented as pydantic models.
Every event has a certain set of top level fields. These are implemented
in the `BaseEvent` class. Every other event should inherit from that
class. The fields every event will have are these:

The values obviously will differ...

```json
{
    "at": "2025-09-24T13:32:19.517600273Z",
    "ns": "Net.InboundGovernor.Remote.InboundGovernorCounters",
    "data": {},
    "sev": "Info",
    "thread": "124",
    "host": "openblockperf-dev-database1"
}
```

The interesting field is `data``, which varies from event to event. There
are many ways to model this. I have started by sublcassing everything and
have every non simple type be its own model. That felt cumbersome. So
Now i changed to just slap a model_validator and populate the fields
i actually only care about into the dict returning from that validator.
See `blockperf.models.events.peer:PeerEvent` as one such example.

Below are some notes on the events i care about. They all only focu on
the data field!

## Inbound Governor

The inbound governor just prints its state ??

```json
{
"data": {
    "idlePeers": 1,
    "coldPeers": 53,
    "warmPeers": 1
    "hotPeers": 0,
    "kind": "InboundGovernorCounters",
}}
```

## Node (Re)start

```json
{
"data": {
    "addresses": [
        {
            "path": "/opt/cardano-node/db/node.socket"
        }
    ],
    "kind": "AcceptPolicyTrace"
}}
```

## Peer Events

Both events below are implemented in PeerEvent. That class uses a model_validator
(from pydantic) and inspects the data field to determine the events local
and remote address and port as well as the connection direction and the
final state the Peer is in.

### The default event

The events:  PromotedTWarm, PromotedToHot, DemotedToWarm, DemotedToCold
all have the same structure. They all have the same `connectionId` field
in the data. The value looks like this:

```json
{
"data": {
    "connectionId": {
        "localAddress": {
            "address": "172.0.118.125",
            "port": "3001"
        },
        "remoteAddress": {
            "address": "85.106.4.146",
            "port": "3001"
        }
    },
}}
```


### The Peer Status Changed

Is a bit special because it does not have the same `connectionId` field
but `peerStatusChangeType`. The value looks different.


```json
{
"data": {
    "peerStatusChangeType": "ColdToWarm (Just 172.0.118.125:3001) 3.228.174.253:6000"
}}
```
