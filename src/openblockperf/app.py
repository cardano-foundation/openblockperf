import asyncio
from collections.abc import Callable

import psutil
import rich
from loguru import logger
from rich.console import Console

# from rich.console import Console
from openblockperf.apiclient import BlockperfApiClient
from openblockperf.blocksamplegroup import BlockSampleGroup
from openblockperf.config import settings
from openblockperf.ekg import EkgClient, EkgError
from openblockperf.errors import (
    ApiConnectionError,
    ConfigurationError,
    EventError,
    InvalidEventDataError,
    StartupMarkerNotFoundError,
    UnknowEventNameSpaceError,
)
from openblockperf.handler import EventHandler
from openblockperf.logreader import NodeLogReader, create_log_reader
from openblockperf.models.peer import Peer, PeerState

# console = Console()


class Blockperf:
    """Implements the Blockperf application.

    The main application loop is built around an asyncio TaskGroup. The
    start() function implements the creation of various needed resources
    (api client, log reader, event handler, etc.) as well as the TaskGroup
    itself. Most functionality of the app is inside one such task with the
    idea being that they all run concurrently (within asyncio).

    * create_task() creates the task in the taskgroup using the provided callable
    * run_task() is what will actually execute (await!) the task.

    The create_task() is just a simple wrapper around the process of calling
    the taskgroups create_task(). It adds the returned task object to the
    list of tasks (Blockperf.tasks). Then  run_task() because that is
    what allows every task to propagate its errors cleanly. This is important
    to do because if the app receives a SIGINT or SIGTERM signal (Users
    presses Ctrl-C), we want all tasks to get properly canceled. But the
    application should not "die in blood". That is, it should exit cleanly.
    The run_task() is what handles the "individual task" exceptions and
    in the start() try/catch block handles "all tasks". Most importantly
    asnyncio.CancelledError. Currently if any of the tasks fail, the whole
    group should fail.
    """

    log_reader: NodeLogReader  # the log reader this processor is using
    console: Console  # The console to write to
    handler: EventHandler  # Handler to handle the different events
    tasks: dict[str, asyncio.Task]  # Holds all apps tasks
    since_hours: int
    block_sample_groups: dict[str, BlockSampleGroup]  # Groups of block samples
    peers: dict[tuple, Peer]  # The nodes peer list (actually a dictionary)
    replaying: bool

    def __init__(self, console: Console, app_settings=None):
        # Keep this simple! Do any complex init in start()
        self.console = console
        self.settings = app_settings or settings()
        self.replaying = False
        self.tasks: dict[str, asyncio.Task] = {}
        self.since_hours = 0
        self.block_sample_groups = {}
        # self._block_sample_groups_lock = asyncio.Lock()
        self.peers = {}
        # self._peers_lock = asyncio.Lock()

        # AsyncIO Events allow coroutines to wait for an event to happen
        self.node_synced_event: asyncio.Event = asyncio.Event()  # Defaults to false (unset)
        if not self.settings.sync_check_enabled:
            # If disabled always, assume the node is synced.
            self.node_synced_event.set()

    def _validate_configuration(self) -> None:
        """Validate application configuration."""
        if not self.settings.check_interval or self.settings.check_interval <= 0:
            raise ConfigurationError("Invalid check_interval in configuration")

    async def start(self):
        """Run all application tasks with proper error handling and coordination."""
        self._validate_configuration()
        self.api = BlockperfApiClient(self.settings)  # Single api client for app
        self.log_reader = create_log_reader("journalctl", "cardano-tracer")
        self.handler = EventHandler(
            self.block_sample_groups,  # Sample Groups the handler will put events into
            self.peers,  # The live list of peers that is being updated by the handler
            self.api,  # Provide api to handler
            self.settings,  # Pass settings for network-specific configuration
        )
        self.ekg = EkgClient(self.settings.ekg_url)

        try:
            async with asyncio.TaskGroup() as tg:
                # Create all long running tasks that run in this app
                self.create_task(self.process_events_task, tg)
                self.create_task(self.testapi_task, tg)
                self.create_task(self.send_block_samples_task, tg)
                self.create_task(self.print_peer_statistics_task, tg)
                self.create_task(self.monitor_sync_state_task, tg)  # ← add this

        except* asyncio.CancelledError as _eg:
            # If the users sends SIGINT, SIGTERM (Ctrl-c) the taskgroup
            # canceles all tasks. Each one will send an CancelledError.
            # Thus this needs to be an exception group catch and rais
            # to signal clean shutdown.
            raise

        except* ApiConnectionError as _eg:
            raise

        except* Exception as eg:
            # If any of the tasks throws and excpetion
            if eg.exceptions:
                logger.error(f"Task group failed with {len(eg.exceptions)} exceptions")
                for exc in eg.exceptions:
                    logger.exception(f"Critical task error: {exc}")
            raise

    async def stop(self):
        """Gracefully stop the application and clean up resources."""
        # Cancel all running tasks
        for task_name, task in self.tasks.items():
            if not task.done():
                self.console.print(f"Cancelling task: {task_name}")
                task.cancel()

        # Wait for tasks to finish cancellation
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    def create_task(
        self,
        func: Callable,
        tg: asyncio.TaskGroup,
    ):
        """Create a task from provided function in the taskgroup provided.

        Stores the task in self.tasks for later access.
        """
        _name = func.__name__
        self.tasks[_name] = tg.create_task(self.run_task(_name, func))

    async def run_task(self, task_name: str, task):
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
        return {name: "running" if not task.done() else "finished" for name, task in self.tasks.items()}

    async def process_events_task(self):
        """Process events from log reader with startup replay capability.

        First replays all historical events since the last service startup,
        then switches to live log tailing. This ensures no events are missed
        and the client starts with a complete picture of the current state.
        """
        self.console.print("Starting event processor")

        async with self.log_reader as log_reader:
            # ===== PHASE 1: BLOCKING REPLAY =====
            # Replay historical logs from last startup. The loop over
            # replay_from_startup() blocks as long as that function does
            # not call `return`. Such that, as long as it yields values
            # the loop will run.

            enable_replay = False
            self.console.print("[bold yellow]Log replaying disabled[/]")
            if enable_replay:
                try:
                    self.console.print("[bold blue]Searching old logs for node startup marker[/]")  # fmt: off
                    message_count = 0  # just counting for now
                    self.replaying = True
                    async for message in log_reader.replay_from_startup():
                        await self._process_message(message)
                        message_count += 1
                except StartupMarkerNotFoundError:
                    self.console.print("[bold red]No startup marker found in logs[/]")  # fmt: off
                finally:
                    self.replaying = False  # flag replaying has finished
                    if message_count > 0:
                        self.console.print(f"Replay completed: processed {message_count} historical messages")

            # ===== PHASE 2: LIVE TAILING =====
            # Now switch to live log tailing, this should run forever
            self.console.print("Starting live log processing...")
            async for message in log_reader.read_messages():
                # The generate will constantly generate messages. We only
                # want to process them though, when we know the node is synced.
                # I wanted to avoid that log messages from the generate keep piling
                # up and then once the node is synced all flush through at once.
                # Thats why there is no `await self.node_synced_event.wait()` call!
                if self.node_synced_event.is_set():
                    await self._process_single_message(message)

    async def _process_single_message(self, message: dict):
        """Processes every incoming message. It does not care about any
        details of these messages. Just receive them, "handle" them,
        and either be happy or throw appropriate errors.

        """
        try:
            # Pass message to handler to handle the event it represents
            await self.handler.handle_message(message)
        # NotInterestedError
        except UnknowEventNameSpaceError:
            pass  # The Messages namespace is not registered as an event
        except InvalidEventDataError:
            self.console.print(f"[bold red]Validation error for {message.get('ns')}[/]")  # fmt: off
        except EventError as e:
            logger.error("Error processing event")
            self.console.print(f"[bold red]Error handling event. {e}[/]")
        except Exception as e:
            logger.exception("Error processing event")
            raise

    async def update_peers_connections_task(self) -> None:
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
                await self.peer_listener.update_peers_from_connections(connections)

    async def update_peers_unknown_task(self) -> None:
        """Update unknown peers by searching the logreader for older messages"""
        # should run after thefirst update_peers_connections did
        while True:
            await asyncio.sleep(20)
            peers = [
                p
                for p in self.peer_listener.peers.values()
                if p.state_inbound == PeerState.UNKNOWN and p.state_outbound == PeerState.UNKNOWN
            ]
            self.since_hours = self.since_hours + 12 if self.since_hours < 2000 else 2000

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
                async for message in self.log_reader.search_messages(peer.remote_addr, since_hours=self.since_hours):
                    if message.get("ns") in self.peer_listener.registered_namespaces:
                        updated += 1
                        # Found a message, insert it and break loop for peer
                        await self.peer_listener.insert(message)
                        break
            self.console.print(f"Found {updated} peers in logs")

    async def send_block_samples_task(self):
        """Checks if block samples are ready and if so sends them to the api.

        the block samples to the server.
        """
        while True:
            await asyncio.sleep(self.settings.check_interval)
            if self.replaying:
                rich.print("Wont send samples coz of the replay")
                continue
            ready_groups = {}
            for k, group in self.block_sample_groups.items():
                if group.is_complete() and group.age_seconds > self.settings.min_age:
                    ready_groups[k] = group

            for k, group in ready_groups.items():
                # If the group is not ok, dont send it
                if not group.is_sane():
                    continue
                # Group is ok, grab and send the sample
                sample = group.sample()
                resp = await self.api.submit_block_sample(sample)
                rich.print(f"[bold green]Sample {group.block_hash[:8]} published. {resp=}.[/]")
                # Delete group
                del self.block_sample_groups[k]

    async def print_peer_statistics_task(self):
        """Print peer statistics periodically."""
        while True:
            await asyncio.sleep(30)
            peers = self.peers.values()

            in_cold = [p for p in peers if p.state_inbound == PeerState.COLD]
            out_cold = [p for p in peers if p.state_outbound == PeerState.COLD]
            in_warm = [p for p in peers if p.state_inbound == PeerState.WARM]
            out_warm = [p for p in peers if p.state_outbound == PeerState.WARM]
            in_hot = [p for p in peers if p.state_inbound == PeerState.HOT]
            out_hot = [p for p in peers if p.state_outbound == PeerState.HOT]
            in_cooling = [p for p in peers if p.state_inbound == PeerState.COOLING]
            out_cooling = [p for p in peers if p.state_outbound == PeerState.COOLING]  # fmt: off
            in_unknown = [p for p in peers if p.state_inbound == PeerState.UNKNOWN]  # fmt: off
            out_unknown = [p for p in peers if p.state_outbound == PeerState.UNKNOWN]
            stats = {
                "in_cold": len(in_cold),
                "out_cold": len(out_cold),
                "in_warm": len(in_warm),
                "out_warm": len(out_warm),
                "in_hot": len(in_hot),
                "out_hot": len(out_hot),
                "in_cooling": len(in_cooling),
                "out_cooling": len(out_cooling),
                "in_unknown": len(in_unknown),
                "out_unknown": len(out_unknown),
                "total_peers": len(self.peers),
            }
            rich.print(stats)

    async def testapi_task(self):
        while True:
            await asyncio.sleep(20)

            print("go")
            await self.api.post_status_change()

    async def monitor_sync_state_task(self) -> None:
        """Polls the node's EKG endpoint and gates ingestion on sync state.

        The self.node_synced_event is what holds the gate. This function
        will update that gate accordingly. Every coroutine that needs to
        check if the node is sync must await that event `await self.node_synced_event
        """

        # If sync check is disabled, there is nothing to do here
        if not self.settings.sync_check_enabled:
            return

        while True:
            try:
                rpl_prg = await self.ekg.get("cardano_node_metrics_blockReplayProgress_real")
                synced = rpl_prg is not None and rpl_prg >= self.settings.sync_check_threshold
                block_replay_progress = f"{rpl_prg:.2f}%" if rpl_prg else "unknown"

                if synced:
                    # Set node_synced_event if its not set
                    if not self.node_synced_event.is_set():
                        rich.print(f"[green]Node fully synced ({block_replay_progress}), resuming log ingestion.[/]")
                        self.node_synced_event.set()
                    else:
                        rich.print(
                            f"[yellow]Node not fully synced ({block_replay_progress}%), pausing log ingestion.[/]"
                        )

                else:
                    pct_str = f"{block_replay_progress:.2f}%" if block_replay_progress is not None else "unknown"
                    if self.node_synced_event.is_set():
                        rich.print(f"[yellow]Node sync dropped ({pct_str}), pausing log ingestion.[/yellow]")
                        self.node_synced_event.clear()
                    else:
                        rich.print(f"[yellow]Waiting for node to sync ({pct_str})...[/yellow]")
            except EkgError as exc:
                # EKG unreachable — treat as not-synced and keep waiting
                if self.node_synced_event.is_set():
                    rich.print(f"[red]EKG unreachable ({exc}), pausing log ingestion.[/red]")
                    self.node_synced_event.clear()
                else:
                    rich.print(f"[red]EKG still unreachable: {exc}[/red]")

            await asyncio.sleep(self.config.sync_check_interval)
