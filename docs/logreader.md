# The LogReader

The client needs to read the logs of the cardano-node. With the release
of 10.6 the old (legacy) tracing system will become deprecated and eventually
will be removed. https://github.com/cardano-foundation/developer-portal/pull/1669

The OpenBlockperf Client does not support that old legacy system. From now
on the `cardano-tracer` service is responsible for the tracing. Read the d
ocs on [New tracing System](https://developers.cardano.org/docs/operators/monitoring/new-tracing-system/cardano-tracer/#cardano-tracer)

The `cardano-tracer` provides at least two ways to retrieve (and store) these
logs from the node. On disk as a file (much like the previous system) and
through the use of journald.

## NodeLogReader abstract base class

The OpenBlockperf Client aims top support different ways of getting
access to a nodes logs. The `blockperf.logreader` module provides an abstract
base class called `NodeLogReader` which is meant to provide the interface for
any log source.

### JournalCtlLogReader

Initially i wanted to use the systemd python library to connect to journald.
But i did not have the success i was hping and had all kinds of different
problems. Thus i implemented this class that just uses the `journalctl` cli
tool to access the nodes logs in journald. Up until now, this has worked pretty
well.


### FileLogReader

Enabled when config sets `tracer_log_file` to an absolute JSON logfile path
(cardano-tracer or node file backend). The reader tails that path, follows
rename/create and copytruncate rotation, and parses one JSON object per line.

**Unit / line filter:** `node_unit_name` is reused as a content filter (not a
systemd unit lookup):

- If a message has `unit` / `syslog_identifier` (or similar), it must equal
  `node_unit_name`.
- Otherwise the raw line must contain `node_unit_name` as a substring.
- Set `node_unit_name` to the tracer JSON `host` field (for example
  `hh-hongkong`), or to `""` to accept all lines.
- Do not leave a systemd unit such as `cnode.service` as the filter unless that
  string appears in each log line; otherwise every line is skipped.

On connect, live tailing seeks to EOF (only new lines after start). Historical
replay still searches for the startup marker
`"ns":"Net.Server.Local.Started"` in the active file.

See [Installer Guide](blockperf-install.md#switching-an-existing-install-to-logfile-mode)
and [Trace Options](blockperf-traceoptions.md#logfile-mode-and-node_unit_name)
for operator configuration.
