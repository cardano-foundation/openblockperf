<!--<p align="center"></p> -->

<p align="center"><strong>OpenBlockperf</strong> <em>- A cli tool to monitor and share network metrics from a cardano-node.</em></p>

<p align="center">
<a href="https://pypi.org/project/openblockperf/">
    <img src="https://badge.fury.io/py/openblockperf.svg" alt="Package version">
</a>
</p>

The OpenBlockperf Client is a cli tool that collects various data points from
a local cardano node. If you dont know what a cardano-node is or dont run one
yourself, this tool is probably not very usefull for you.

---

## Installation / Get started

You will need a `cardano-node` and and the `cardano-tracer` up and running.
Read up on the details here [in the developer portal](https://developers.cardano.org/docs/operate-a-stake-pool/node-operations/new-tracing-system/new-tracing-system).

Install openblockperf client from pypi.


```shell
$ pip install openblockperf
# Or 'uv pip install" if you prefer

# Once installed you should have a 'blockperf' executable installed.
$ blockperf version
```

