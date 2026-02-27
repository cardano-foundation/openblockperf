# Introduction

The OpenBlockperf Client collects various data points from a running cardano-node.
It reads the nodes logs and collects the entries it is interested in. These
can be categorize into three main parts.

* **Block timings** is about measuring different times regarding to a specific block.
    See blocksamples.md
* **Node Peers** is about monitoring the peers a node is connected to.
    See peers.md
* **Transactions** is about the transactions this node sees and has seen.
    Transactions have not been implemented yet

Everything is specific to the local cardano-node this client is supposed to
run with.

## OpenBlockperf API

The OpenBlockperf client collects the data and sends it to the api.

### API Key

To access that api, the client needs to have an api key.

### Client UUID

Every client creates a uuid, which will be stored locally. Should that
uuid be deleted, then the client will simply generate a new one. The
user should not need to worry about this at all. The idea behind this is
to allow the server to uniquely identify each client. The API Key alone
would not be able to do that, because we assume that people might not want
to issue individual keys for all their relays but just have one that they
share among them. But uniquely identifiying each client is important to
better understand the peer connections and its access to the cardano network.
