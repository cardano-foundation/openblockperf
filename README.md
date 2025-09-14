<!--<p align="center"></p> -->

<p align="center"><strong>OpenBlockperf</strong> <em>- A cli tool to collect and share cardano network metrics.</em></p>

<p align="center">
<a href="https://pypi.org/project/openblockperf/">
    <img src="https://badge.fury.io/py/openblockperf.svg" alt="Package version">
</a>
</p>

The OpenBlockperf Client is a cli tool that collects various metrics from
a cardano node. If you dont know what a cardano-node is or dont run one
yourself, this tool is probably not for you.

---

Install OpenBlockperf using pip:

```shell
$ pip install openblockperf
```

## Get started

* You will need a `cardano-node` and and the `cardano-tracer` up and running.
* Set the network via the `NETWORK` environment variable.
* If you have not yet started to use uv i highly recommend you do. See https://docs.astral.sh/uv/getting-started/installation/

```shell
export NETWORK="mainnet"
blockperf run
```

## Dependencies

We have tried to keep the dependencies as little as possible. Thi

  * `typer` - We use typer to implement the cli interface
  * `click` - Typer itself relies on the click library
  * `pydantic` - For json (and other data) validation
  * `pydantic-settings` - For the applications configuration

