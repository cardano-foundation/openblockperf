# Introduction

This is a fairly technical documentation about the things that i am building.
For me as a reference and for the interested reader to learn about blockperf.
Whenever i talk about blockperf i mean the client that is running alongside
the node.

Roughly speaking blockperf needs to do the following

* Ingest logs from the node, from either the node.json link or the journd logstream.
* Store all these logs... in a local sqlite? Just in memory? -> In memory sqlite?!
    Every log is some kind of event that has happened in the node.
* From all these logs, filter out the ones that we want to see. The node
    can and does provide a lot of things in its logs but we are only interested
    in some.
* That filtering will need to happen regularly, I want to see a specific
    set of events for every block.
* * That set of events can take a long time until its completed.
* * It may never happen for a given block

* Collect all events for a given block (group by block). Then preprocess
    that "blockevent". And store it?
* Then send that data sample in.

## Components

* **Log Parser** The log parser is able to ingest logs from various sources.
    It is not required to be able to use more than one source at a time.
    It
