# The LogReader

The client needs to read the logs of the cardano-node. With the release
of 10.6 the old (legacy) tracing system will become deprecated and eventually
will be removed. https://github.com/cardano-foundation/developer-portal/pull/1669

The OpenBlockperf Client does not support that old legacy system. From now
on the `cardano-tracer` service is responsible for the tracing. Read the d
ocs on [New tracing System](https://developers.cardano.org/docs/operate-a-stake-pool/node-operations/new-tracing-system/new-tracing-system)

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

The tracer also supports writing to files. This class should implement reading
from the files. But its not implemented yet.
