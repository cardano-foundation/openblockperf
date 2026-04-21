

**OpenBlockperf** *- A cli tool and systemd service to capture and share network metrics from a cardano relay node.*



The OpenBlockperf Client is a cli tool that collects various data points from
a local Cardano relay node, run by a stake pool operator. If you are setting up or
operating a stake pool, start with this guideline:
[https://developers.cardano.org/docs/operate-a-stake-pool/](https://developers.cardano.org/docs/operate-a-stake-pool/)

openBlockperf is designed to run on relay nodes located between the stake pool 
(producer) node and the global network. It can also run on producer nodes if 
desired, albeit it is not recommended. In normal operation, OpenBlockperf runs
as a systemd service. OpenBlockPerf watches and monitors the global data flow
between the relay nodes of different stake pools.

---

## Installation / Get started

The installer targets Linux environments typically used for Cardano nodes
(for example Ubuntu/Debian server setups with systemd) and requires some specific 
traceOptions enabled in the configuration (see [Trace Options Guide](docs/blockperf-traceoptions.md) )

Install OpenBlockperf with the installer script below, or alternatively
- See [Installer Guide](docs/blockperf-install.md) for all installer modes and options.
- See [Manual Installation Guide](docs/blockperf-install-manual.md) for step-by-step manual setup.
- See [OpenBlockPerf Client Overview](docs/blockperf-client.md) for a high-level explanation of what the client does and why the shared telemetry matters.

```bash
curl -fsSL https://raw.githubusercontent.com/cardano-foundation/openblockperf/main/blockperf-install.sh -o blockperf-install.sh
chmod +x blockperf-install.sh
sudo ./blockperf-install.sh
```

### interactive

By default this starts an interactive command line wizard that guides you step 
by step through the installation and configuration:

```console
OpenBlockPerf installer overview
  Version: 0.1.1
  1) Check/install prerequisites (Debian/Ubuntu and RHEL-family)
  2) Resolve service user/group, node name, and cardano-node unit/config
  3) Resolve network and API-key strategy
  4) Install venv/package, write env+unit+wrapper, enable service
  5) Print summary and next steps

Continue? [y/N]: y

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Step 1/5  Check/install prerequisites...

[INFO]  Verifying: Python (python3), jq, curl, systemd, core utilities, ensurepip...
[INFO]    Status: satisfied — no extra OS packages needed.
[ OK ]  All prerequisites are ready.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Step 2/5  Configure service user, node name, cardano-node unit and config...

[INFO]  Using Python 3.12 (python3)
[INFO]  determining openblockperf service identity (user and group)
Service user [user1] (Enter to keep):
Service group [user1] (Enter to keep):
[INFO]  Service identity: user1:user1

You can contribute blockperf data from multiple relay nodes and assign them individual
names for your internal use only. These names will not be shared publicly.
This systems name [relay-seoul]:
[INFO]  Node name: relay-seoul

[INFO]  Cardano node unit: cnode.service
[INFO]  Node config: /opt/cardano/cnode/files/config.json (from cnode.service ExecStart/Environment)
[ OK ]  Node config JSON OK (/opt/cardano/cnode/files/config.json).
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Step 3/5  Configure network and API key...

[INFO]  Network: mainnet (from Shelley genesis networkMagic)
Do you already have a Blockperf API key? [y/N]: y
Enter OPENBLOCKPERF_API_KEY value (input hidden):

OpenBlockPerf Installer (install)
  Version:       0.1.2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Install dir:   /opt/cardano/openblockperf
  Python:        python3
  Package:       openblockperf
  Service user:  user1:user1
  Node name:     relay-seoul
  Node unit:     cnode.service
  Node config:   /opt/cardano/cnode/files/config.json
  Network:       mainnet
  API key:       set
  Service file:  /etc/systemd/system/openblockperf.service
  Env file:      /etc/default/openblockperf
  Command:       /usr/local/bin/blockperf
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Step 4/5  Install virtualenv, package, env file, systemd unit, and wrapper...

[ OK ]  Creating installation directory: /opt/cardano/openblockperf
[INFO]  Changing ownership of /opt/cardano/openblockperf to mtn:mtn before venv/pip (pip runs as this user).
[ OK ]  Creating virtual environment at /opt/cardano/openblockperf/venv ...
[ OK ]  Installing openblockperf from PyPI ...
[ OK ]  Ownership of /opt/cardano/openblockperf set to mtn:mtn.
Environment file /etc/default/openblockperf already exists. Replace with a new file from this run, or keep the existing file? [R/k] (default R):
[ OK ]  Replacing existing environment file: /etc/default/openblockperf
[ OK ]  Writing environment file: /etc/default/openblockperf

[ OK ]  Writing systemd unit: /etc/systemd/system/openblockperf.service
[ OK ]  Writing wrapper command: /usr/local/bin/blockperf
[ OK ]  Reloading systemd daemon ...
[ OK ]  Enabling openblockperf.service ...
Created symlink /etc/systemd/system/multi-user.target.wants/openblockperf.service → /etc/systemd/system/openblockperf.service.
[ OK ]  Service enabled. To start use 'systemctl start openblockperf.service'.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Step 5/5  Optional service start and installation summary...

Start openblockperf.service now (API key is configured)? [y/N]: y
[ OK ]  Started openblockperf.service.

Installation complete.

Next steps (API key not set in this run):
  1. Register and obtain an API key:
       /opt/cardano/openblockperf/venv/bin/blockperf register
     A Calidus key is required; 
  2. Set OPENBLOCKPERF_API_KEY in /etc/default/openblockperf
  3. Start the service:  systemctl start openblockperf.service
  4. Status:  systemctl status openblockperf.service
  5. Logs:    journalctl -fu openblockperf.service
```

Once installed you should have a 'blockperf' executable installed.

```console
$ blockperf version
Installed version: 0.0.25
Python version: 3.12.3 
Platform: Linux-6.8.0-100-generic-x86_64-with-glibc2.39
```

### non-interactive

You can also run the installer in non-interactive mode with command line
options, or predefine settings via environment variables (useful for
containerized/deployment automation workflows: see [Installer Guide](docs/blockperf-install.md)). 

When no explicit API key is provided, non-interactive `--yes` now defaults to
`--api-key-mode relay` and attempts automatic public-IP registration.
You can force legacy behavior with `--api-key-mode calidus`.

### install result

- systemd unit: `openblockperf.service`
- env file: `/etc/default/openblockperf`
- CLI wrapper: `/usr/local/bin/blockperf`
- app install + venv: `/opt/cardano/openblockperf`
- logs: `journalctl -fu openblockperf.service`

### Updates

Use update mode to check for both installer and OpenBlockperf client updates and
install them if confirmed.

```bash
sudo ./blockperf-install.sh --update
```

## blockperf usage

The installer configures and starts OpenBlockperf as a systemd service, which
is the recommended way to run it continuously on node hosts.

You can also run it in your console for tests and explorations

Usage Examples:

```shell
  # Use mainnet (default)
  blockperf run

  # Use preprod network
  blockperf run --network preprod

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

Initial operator identification uses the 
[Calidus Stake Pool Key](https://forum.cardano.org/t/new-calidus-pool-key-for-spos-and-services-interacting-with-pools/143812):

You can generate and register your own stake pools Calidus key for example 
with this [SPO script](https://github.com/gitmachtl/scripts/blob/master/cardano/mainnet/15_calidusPoolKey.sh) 
or by using the CNTools text UI (Pool > Calidus > ...) 

During registration the `blockperf register` command gets a challenge and will sign it with your
Calidus key. The provided API key is assigned to this Calidus Keys Stakepool(s). 

```bash
blockperf register --pool-id [your pools bech32 id] --calidus-skey [path to your calidus skey file]
```

For public relay IP-bound registration (IPv4/IPv6 probes as available), use:

```bash
blockperf register --relay-ip
```

Relay-IP registration is intended for operators without stake-pool credentials
who want to participate with a single relay node.
For SPO-level participation across a whole pool infrastructure (multiple relays
reported as one entity), use a Calidus-registered API key.

You only need to run the register command and provide your Calidus skey once 
on one of your relay nodes to obtain the API key for your stake pool. 
After that, you can copy and use this API key on additional relay nodes. 

## Uninstall

When openBlockperf is no longer needed, it can be completely removed using the `blockperf-install.sh --remove` parameter. 