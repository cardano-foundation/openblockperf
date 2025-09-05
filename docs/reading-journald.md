# Reading from journald

Assuming the cardano-tracer writes its logs to journald. I wanted the
client to be able to just connect to journald and read from there. It
removes the burden of having to manage log files. The implementation
of "tailing a logfile, that is actually a symlink" was a pain in the butt
so i welcome journald as intermediate allowing me to just receive the constant
stream of log events from there.

## Accessing journal from python

I am using the [systemd-python](https://github.com/systemd/python-systemd)
library to access journald.

* **Note**
*
* Make sure that whoever you run this as is able to access journald.
* If that is not possible, it will not work. :p
* To enable a user to read from journald you need to add that user to
* the `systemd-journal` group. `sudo gpasswd -a USER systemd-journal`
*

### Reader setup

To read from journald you need to create a reader. That reader will provide
access to all the messages in journald similar to what a simple invocation
of `journalctl` would show. In this case though we are only interested in
all messages from a specific service (*cardano-tracer*). In the cli you
would provide the `-u SERVICE` flag to specify the service you are interested
in. In systemd-python there is the concept of *matchers*. You add matchers
to the reader to filter the messages it is able to see.

```python
from systemd import journal

# Create the reader
reader = journal.Reader()

# Add matcher to match a specific unit, similar to journalctl -u UNIT
reader.add_match(_SYSTEMD_UNIT="cardano-tracer")
# or e.g.: reader.add_matcher(SYSLOG_IDENTIFIER="cardano-tracer")
# This will make the reader only see messages that match

# Move to the end if you want to
reader.seek_tail()
```

Now the reader should be able to

```python

while True:
    entry = reader.get_next()
    if entry:
        print(entry)
    else:
        w = reader.wait() # waits forever


```


