# OpenBlockperf Client

The OpenBlockperf Client is a tool that allows to collect certain metrics from
a cardano-node, pre-processes them and then sends this data to a rest api.


* The client needs to constantly read from either journald or a file the log
  messages of the node. I need some abstraction over where these logs come
  from that can be configured.

* When ingesting these log lines i need a pydantic Model (or more?) that
  can validate that all fields


## python modules

The following are the modules of the application:

### cli 

Takes care of all the cli parsing and using the different aspects of the application

### app

Implements the application as a class. This class will be used in the different
ways that the cli interface provides. Which will mostly be 

### client

Will implement the openblockperf backend client. It provides an abstraction
over the openblockperf api and its use. 


## Registration

The client can either be registered as an SPO or as an anonymous relay. Either
way it needs to register with the server to receive a client id. 