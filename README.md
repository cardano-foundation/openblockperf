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

Install openblockperf client using our installer script:

```shell
curl -fsSL https://raw.githubusercontent.com/cardano-foundation/openblockperf/main/install.sh | sudo bash

# Once installed you should have a 'blockperf' executable installed.
$ blockperf version
```


## Usage

To run the client you need to specify which network it is in.

Usage Examples:

```shell
  # Use mainnet (default)
  blockperf run

  # Use preprod network
  blockperf run --network preprod

  # Use preview network
  blockperf run -n preview

  # Override API URL for local development
  blockperf run --api-url http://localhost:8000

  # Combine network with custom API URL
  blockperf run --network mainnet --api-url https://custom-api.example.com

  # Or use environment variable
  export OPENBLOCKPERF_NETWORK=preprod
  blockperf run
```

## Registration

To register for an api key, you need to have a calidus key registered on chain.
Then use the `blockperf register` command to start the registration. That
You will receive a challenge that you will need to sign with your calidus
key. Then submit that signature back to the api to receive the apikey.

```bash
blockperf register --
```
