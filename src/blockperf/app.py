import asyncio
from datetime import datetime

import psutil
import rich
from loguru import logger
from rich.console import Console

# from rich.console import Console
from blockperf.apiclient import BlockperfApiClient
from blockperf.config import settings
from blockperf.errors import BlockperfError, ConfigurationError, TaskError
from blockperf.listeners.block import BlockListener
from blockperf.listeners.peer import PeerListener
from blockperf.logreader import NodeLogReader, create_log_reader
from blockperf.models.peer import PeerState
from blockperf.processor import EventProcessor

# console = Console()


class Blockperf:
    log_reader: NodeLogReader  # the log reader this processor is using
    console: Console
    since_hours: int

    def __init__(self, console: Console):
        try:
            # Validate configuration early
            self._validate_configuration()
            self.console = console
            self.log_reader = create_log_reader("journalctl", "cardano-tracer")
            self.block_listener = BlockListener()
            self.peer_listener = PeerListener()
            # Tracks running tasks for cleanup
            self._tasks: dict[str, asyncio.Task] = {}
            self.since_hours = 0

        except Exception as e:
            logger.opt(exception=True).debug(f"Initialization failed: {e}")
            raise ConfigurationError(f"Initialization failed: {e}") from e

    def _validate_configuration(self) -> None:
        """Validate application configuration."""
        config = settings()
        if not config.check_interval or config.check_interval <= 0:
            raise ConfigurationError("Invalid check_interval in configuration")

    async def start(self):
        """Run all application tasks with proper error handling and coordination."""
        self.console.print("Starting Blockperf application")

        try:
            async with asyncio.TaskGroup() as tg:
                # Create tasks with names for better error tracking
                self._tasks["event_processor"] = tg.create_task(
                    self._run_task("event_processor", self.process_events)
                )
                # self._tasks["update_peers_connections"] = tg.create_task(
                #    self._run_task(
                #        "update_peers_connections",
                #        self.update_peers_connections,
                #    )
                # )
                # self._tasks["update_peers_unknown"] = tg.create_task(
                #    self._run_task(
                #        "update_peers_unknown", self.update_peers_unknown
                #    )
                # )
                self._tasks["block_sender"] = tg.create_task(
                    self._run_task("block_sender", self.send_block_samples)
                )
                self._tasks["stats_printer"] = tg.create_task(
                    self._run_task("stats_printer", self.print_peer_statistics)
                )

        except* asyncio.CancelledError as eg:
            self.console.print("Tasks cancelled - shutdown initiated")

        except* Exception as eg:
            if eg.exceptions:
                logger.error(
                    f"Task group failed with {len(eg.exceptions)} exceptions"
                )
                for exc in eg.exceptions:
                    logger.error(f"Critical task error: {exc}")
                    raise exc

    async def stop(self):
        """Gracefully stop the application and clean up resources."""
        self.console.print("Stopping Blockperf application")

        # Cancel all running tasks
        for task_name, task in self._tasks.items():
            if not task.done():
                self.console.print(f"Cancelling task: {task_name}")
                task.cancel()

        # Wait for tasks to finish cancellation
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        self.console.print("Blockperf application stopped")

    async def _run_task(self, task_name: str, task):
        """Wrapper that provides consistent error handling for all tasks."""
        try:
            await task()
        except asyncio.CancelledError:
            logger.debug(f"Task '{task_name}' was cancelled")
            raise  # Re-raise CancelledError as it's expected during shutdown
        except Exception as e:
            logger.error(f"Task '{task_name}' failed: {e}")
            raise  # Fail fast - any task failure crashes the app

    def _tasks_status(self) -> dict[str, str]:
        """Get status of all running tasks for debugging."""
        return {
            name: "running" if not task.done() else "finished"
            for name, task in self._tasks.items()
        }

    async def process_events(self):
        """Continiously processes the events coming from the log reader.

        First opens the context for the logreader which calls connect() on
        it. Then enters a loop to iterate over all messages of the logreader
        forever. The read_messages() funcion is meant to be a generator which
        will continiously yield new log messages. See NodeLogReader base
        class which provides the abstract interface.
        """
        self.console.print("Starting event processor")
        async with self.log_reader as log_reader:
            async for message in log_reader.read_messages():
                # event = parse_log_message(message)
                ns = message.get("ns")
                # if ns == "Net.Server.Local.Started":
                #    # Do some special thing on a restart?
                #    continue

                if ns in self.block_listener.registered_namespaces:
                    await self.block_listener.insert(message)
                if ns in self.peer_listener.registered_namespaces:
                    await self.peer_listener.insert(message)
                # self.collector.add_event(event)

    async def update_peers_connections(self) -> None:
        """Updates peers from the the connections list.

        Compares the list of peers with current active connections on the
        system. The idea being that especially on startup, there might already
        be alot of peers in the node, that we will never get notified about.
        This adds peers to that list with a state of unknown.
        """
        while True:
            await asyncio.sleep(10)  # wait at least 60 seconds before first run
            connections = []
            for conn in psutil.net_connections():
                if conn.status != "ESTABLISHED":
                    continue
                if conn.laddr.port != 3001:
                    continue
                addr, port = conn.raddr
                connections.append(conn)

            if connections:
                await self.peer_listener.update_peers_from_connections(
                    connections
                )

    async def update_peers_unknown(self) -> None:
        """Update unknown peers by searching the logreader for older messages"""
        # should run after thefirst update_peers_connections did
        while True:
            await asyncio.sleep(20)
            peers = [
                p
                for p in self.peer_listener.peers.values()
                if p.state_inbound == PeerState.UNKNOWN
                and p.state_outbound == PeerState.UNKNOWN
            ]
            self.since_hours = (
                self.since_hours + 12 if self.since_hours < 2000 else 2000
            )

            # If there are no unknown, no need to update
            if not peers:
                continue

            self.console.print(
                f"Search {len(peers)} peers in state UNKNOWN in logs of the last {self.since_hours} hours"
            )
            updated = 0
            for peer in peers:
                # Trying to not search the whole history at once.
                # The more iterations there are the less peers and the longer the
                # time period to search in for.

                # BUT: There is a bug here !!!!!
                # I need to make sure that the message found also matches
                # the port!!!!
                async for message in self.log_reader.search_messages(
                    peer.remote_addr, since_hours=self.since_hours
                ):
                    if (
                        message.get("ns")
                        in self.peer_listener.registered_namespaces
                    ):
                        updated += 1
                        # Found a message, insert it and break loop for peer
                        await self.peer_listener.insert(message)
                        break
            self.console.print(f"Found {updated} peers in logs")

    async def send_block_samples(self):
        """The BlockListener collects samples, send_blocks sends these to the api."""
        while True:
            await asyncio.sleep(settings().check_interval)
            async with BlockperfApiClient() as api:
                await self.block_listener.send_block_samples(api)

    async def print_peer_statistics(self):
        """Print peer statistics periodically."""
        while True:
            await asyncio.sleep(30)
            stats = self.peer_listener.get_peer_statistics()
            rich.print(stats)
