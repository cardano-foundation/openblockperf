# Blocksample

The blockperf client calculates blocksamples and sends these the backend.
A blocksample is calculated for each block and holds:

* The ip address and port from where a header of this block was first seen
  (**headerRemoteAddr**, **headerRemotePort**).

* The ip address and port from where the block was downloaded from
  (**blockRemoteAddress**, **blockRemotePort**).

* The time difference between when this block could have been available versus
  when the node actually first got notice of it. That is the difference betwenn
  the time this block was produced (slot time) to the time this node
  receive a header for it the first time. That is the **headerDelta**.

* The time difference between when this node first got notice of this block
  (the time when it first received a header) vs when the node asked for the
  block to get downloaded (send a fetch request). That is the **blockReqDelta**.

* The time difference between when this node first asked for a block versus
  when it did actually finished downloading the block. That is **blockRspDelta**.

* The time difference between when this node completed the download of a
  block versus when it was actually adopted (by this node). That is **blockAdoptDelta**.

There are other values which are pretty obvious. Here is an example payload
from the blockperf.py implementation

```json
{
    "magic": The network magic
    "bpVersion": The version of the client,
    "blockNo": The block number
    "slotNo": The slot number of the block
    "blockHash": the hasah of the block
    "blockSize": the size of the block in bytes
    "headerRemoteAddr": ip address of remote the header was first received from
    "headerRemotePort": port of remote the header was first received from
    "headerDelta": The difference between when
    "blockReqDelta": str(sample.block_request_delta),
    "blockRspDelta": str(sample.block_response_delta),
    "blockAdoptDelta": str(sample.block_adopt_delta),
    "blockRemoteAddress": str(sample.block_remote_addr),
    "blockRemotePort": str(sample.block_remote_port),
    "blockLocalAddress": str(self.app_config.relay_public_ip),
    "blockLocalPort": str(self.app_config.relay_public_port),
    "blockG": str(sample.block_g),
}
```
