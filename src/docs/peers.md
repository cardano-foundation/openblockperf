# Tracking peers

The client tracks the nodes peers by reading through the nodes logs.
We are interested in all the peers the node is connected to. But also
when these peers change their states. That is



## Peer status changes



* Every peer can be in one of many states. See `blockperf.models:PeerState`
* A peer is either outbound or inbound. That is either the node connected
    to the peer or the peer connected to the node. See `blockperf.models:PeerDirection`


## Peers from the OS

When the client starts, the node will probably already run. The client
looks at the current active network connections of the node. It then adds
peers for each connection (if not already in peers list) with the state "UNKNOWN".

Only when a peer sees a status change (or for some other reasons shows up in the
event logs) the status can be set. Therfor i think we need to implement a
mechanism that goes through the old logs and searches for that peer. To then
set the peers state accordingly. https://github.com/cardano-foundation/openblockperf/issues/5

The above is implemented in a task `task_update_peers` which is running
every 30 seconds. But it should also check that the peers in the client
somewhat match the connections seen on the host. Thus it removes those
peers from the peers list for which it can not find any established(!)
connection.


## Peer Messages

There are the following messages in the logs. Many of the are self explanatory.
The StatusChanged needs more explanation

### StatusChangedEvent

* The status change is encoded in the message of the `peerStatusChangeType` field.
* Represents state changes for existing connections and new connections.
* Holds a state transition which can be on of the possible Transitions

### PromotedToWarmRemoteEvent

### PromotedToHotRemoteEvent

### DemotedToColdRemoteEvent

### DemotedToWarmRemoteEvent

### InboundGovernorCountersEvent

