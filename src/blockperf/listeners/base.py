import abc

import rich


class EventListener(abc.ABC):
    """
    Abstract Base Class for log readers.  Provides the general interface
    that all LogReaders must implement.
    """

    registered_namespaces = {}

    @abc.abstractmethod
    async def insert(self, message) -> None:
        """A message arrived from the processor.

        The processor checkd registered_namespaces and inserts the message
        when the ns match a record from there. It still is the raw message
        though and the listener needs to implement what he wants to do with
        the message. First thing is probably try to convert it to a model."""
        pass

    # @abc.abstractmethod
    # async def close(self) -> None:
    #    """Close the connection to the log source."""
    #    pass

    def make_event(self, message):
        ns = message.get("ns")
        if (
            not self.registered_namespaces
            or ns not in self.registered_namespaces
        ):
            # Should never happen ...
            raise RuntimeError("Inserted event not found in registry")

        event_model_class = self.registered_namespaces.get(ns)
        return event_model_class(**message)
