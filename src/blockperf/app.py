import asyncio
from datetime import datetime

import psutil
import rich
from loguru import logger

# from rich.console import Console
from blockperf.apiclient import BlockperfApiClient
from blockperf.config import settings
from blockperf.listeners.block import BlockListener
from blockperf.listeners.peer import PeerListener
from blockperf.processor import EventProcessor

# console = Console()


class Blockperf:
    def __init__(self):
        # The app creates an event processor
        self.event_processor = EventProcessor()

        # There are multiple listeners, that are add to that processor.
        # Each whith its own set of events it wants to listen for.
        # They hold their "usecase relevant" data in their own instance
        self.block_listener = BlockListener()
        self.event_processor.add_listener(self.block_listener)
        self.peer_listener = PeerListener()
        self.event_processor.add_listener(self.peer_listener)

    async def start(self):
        """Run all application tasks"""

        try:
            async with asyncio.TaskGroup() as tg:
                # All tasks at the same level
                tg.create_task(self.event_processor.process_events())
                tg.create_task(self.update_peers_from_connections())
                tg.create_task(self.send_block_samples())
                tg.create_task(self.print_peer_statistics())
                # Add any other top-level tasks here

        except* asyncio.CancelledError:
            logger.info("Application cancelled, shutting down")
        except* Exception as eg:
            for exc in eg.exceptions:
                logger.exception("Task failed", exc_info=exc)
            raise

    async def stop(self):
        """Stops the event processor."""
        logger.info("Blockperf shutdown")

    async def update_peers_from_connections(self) -> list:
        """Updates the connections list.

        Compares the list of peers with current active connections on the
        system. The idea being that especially on startup, there might already
        be alot of peers in the node, that we will never get notified about.
        This adds peers to that list with a state of unknown.

        Later on we might search for these peers in the logs to get their
        current state in the node. Since i dont see us being able to ask
        the node directly anytime soon.
        """
        while True:
            connections = []
            for conn in psutil.net_connections():
                if conn.status != "ESTABLISHED":
                    continue
                if conn.laddr.port != 3001:
                    continue
                addr, port = conn.raddr
                connections.append(conn)

            await self.peer_listener.update_peers_from_connections(connections)
            await asyncio.sleep(30)  # add peers every 5 Minutes

    async def send_block_samples(self):
        """The BlockListener collects samples, send_blocks sends these to the api."""
        try:
            while True:
                await asyncio.sleep(settings().check_interval)
                async with BlockperfApiClient() as api:
                    await self.block_listener.send_block_samples(api)
        except Exception:
            logger.exception("Fatal error in send_blocks")

    async def print_peer_statistics(self):
        while True:
            await asyncio.sleep(30)
            stats = self.peer_listener.get_peer_statistics()
            rich.print(stats)
