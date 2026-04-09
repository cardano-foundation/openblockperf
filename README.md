<!--<p align="center"></p> -->

<p align="center"><strong>OpenBlockperf</strong> <em>- A cli tool to monitor and share network metrics from a cardano-node.</em></p>

<p align="center">
<a href="https://pypi.org/project/openblockperf/">
    <img src="https://badge.fury.io/py/openblockperf.svg" alt="Package version">
</a>
</p>

The OpenBlockperf Client is a cli tool that collects various data points from
a local Cardano node run by a stake pool operator. If you are setting up or
operating a stake pool, start with this guideline:
https://developers.cardano.org/docs/operate-a-stake-pool/

openBlockperf is designed to run on relay nodes located between the stake pool 
(producer) node and the global network. It can also run on producer nodes if 
desired. 

---

## Installation / Get started

The installer targets Linux environments typically used for Cardano nodes
(for example Ubuntu/Debian server setups with systemd).

Install OpenBlockperf with the installer script. By default this starts an
interactive command line wizard that guides you step by step through the
installation and configuration:

```shell
curl -fsSL https://raw.githubusercontent.com/cardano-foundation/openblockperf/main/blockperf-install.sh | sudo bash

# Once installed you should have a 'blockperf' executable installed.
$ blockperf version
```

You can also run the installer in non-interactive mode with command line
options, or predefine settings via environment variables (useful for
containerized/deployment automation workflows). During installation,
OpenBlockperf needs to know:

- the path to the Cardano node `config.json`
- the Cardano node systemd unit name whose journald logs should be read

See `docs/blockperf-install.md` for all installer modes and options.


## Usage

The installer configures and starts OpenBlockperf as a systemd service, which
is the recommended way to run it continuously on node hosts.

You can also run it in your console for tests and explorations

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

Service activity and common file locations:

```shell
# Check service state
sudo systemctl status openblockperf.service

# Follow OpenBlockperf logs
sudo journalctl -fu openblockperf.service

# Typical service env file location
/etc/default/openblockperf

# Typical Client UUID state
~/.local/state/blockperf/clientid.uuid
```

## Registration

OpenBlockperf is built around a shared global view: distributed stake pool
operators submit relay-side block samples and peering events into a common
backend. In return, each contributing operator gets insights about their own
block propagation and relay connectivity.

To contribute data, each stake pool registers once and receives an API key
that can be reused across all of its relay nodes.

Initial operator identification uses the Calidus Stake Pool Key:
https://forum.cardano.org/t/new-calidus-pool-key-for-spos-and-services-interacting-with-pools/143812

During registration, `blockperf register` returns a challenge to sign with your
Calidus key. Submit the signature to receive your OpenBlockperf API key.

```bash
blockperf register --pool-id [your pools bech32 id] --calidus-skey [path to your calidus skey file]
```

You only need to run calidus skey once on one of your relay nodes to obtain the API key for 
your stake pool. After that, you can use this API key on additional relay nodes. 