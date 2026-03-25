"""Ekg metrics scraper.

Fetches the Ekg text exposition endpoint and provides access to
individual metric values by name. No data is stored — every call to
``get()`` / ``get_many()`` issues a fresh HTTP request.

Typical usage::

    client = EkgClient("http://localhost:12798/metrics")
    mempool = await client.get("cardano_node_metrics_txsInMempool_int")
    block   = await client.get("cardano_node_metrics_blockNum_int")

    # Fetch once, read many
    values = await client.get_many([
        "cardano_node_metrics_txsInMempool_int",
        "cardano_node_metrics_blockNum_int",
    ])
"""

import re

import httpx
from pydantic import BaseModel, ValidationError

from openblockperf.logging import logger

# ---------------------------------------------------------------------------
# Prometheus text format parser
# ---------------------------------------------------------------------------
# Spec: https://prometheus.io/docs/instrumenting/exposition_formats/
#
# Each non-comment line follows one of these shapes:
#   metric_name value
#   metric_name{k="v",...} value
#   metric_name{k="v",...} value timestamp
#
# value can be a float, +Inf, -Inf, or NaN.

_SAMPLE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"(?P<labels>\{[^}]*\})?"
    r"\s+(?P<value>[-+]?(?:Inf|NaN|[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?))"
)
_LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


class MetricSample(BaseModel):
    """A single sample parsed from a Prometheus exposition line."""

    name: str
    labels: dict[str, str]
    value: int | float


def parse(text: str) -> list[MetricSample]:
    """Parse Prometheus text exposition format into a list of MetricSamples.

    Comment lines (``#``) and blank lines are ignored. Lines that do not
    match the expected format are logged as warnings and skipped.
    """
    samples = []
    for line in text.splitlines():
        line = line.strip()  # noqa: PLW2901
        if not line or line.startswith("#"):
            continue
        sample = _parse_line(line)
        if sample is not None:
            samples.append(sample)
    return samples


def _parse_line(line: str) -> MetricSample | None:
    """Parse"""
    match = _SAMPLE_RE.match(line)
    if not match:
        logger.warning(f"could not parse line: {line!r}")
        return None

    name = match.group("name")
    label_str = match.group("labels") or ""
    labels = dict(_LABEL_RE.findall(label_str))
    value = match.group("value")

    try:
        sample = MetricSample(name=name, labels=labels, value=value)
        return sample
    except ValidationError:
        logger.warning(f"could not validate sample for: {line!r}")
        return None


class EkgClient:
    """Async client for the ekg endpoint of cardano-node.

    Args:
        url:     Full URL to the metrics endpoint, e.g.
                 ``http://localhost:12798/metrics``.
        timeout: HTTP request timeout in seconds (default 5 s).
    """

    def __init__(self, url: str, timeout: float = 2.0) -> None:
        self.url = url
        self.timeout = timeout

    async def fetch(self) -> list[MetricSample]:
        """Fetch the endpoint and return all parsed samples."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(self.url)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise EkgError(f"Endpoint returned {e.response.status_code}: {self.url}") from e
            except httpx.ConnectError as e:
                raise EkgError(f"Could not connect to {self.url}") from e
            except httpx.TimeoutException as e:
                raise EkgError(f"Request timed out: {self.url}") from e

        return parse(response.text)

    async def get(self, name: str) -> int | float | None:
        """Fetch and return the value of a single named metric.

        Args:
            name: The name of the metric to fetch the value from.
        """
        for sample in await self.fetch():
            if sample.name == name:
                return sample.value

        logger.debug(f"metric '{name}' not found at {self.url}")
        return None

    async def get_many(self, names: list[str]) -> dict[str, int | float | None]:
        """Fetch the endpoint once and return values for multiple metrics.

        Returns a dict keyed by the requested names. A value of ``None``
        means that metric was not present in the response.  When a metric
        appears more than once (e.g. with different label sets) the first
        occurrence is returned.

        Args:
            names: A list of names of the metrics to fetch the values from.
        """
        result: dict[str, int | float | None] = dict.fromkeys(names, None)
        for sample in await self.fetch():
            if sample.name in names:
                result[sample.name] = sample.value

        return result

    async def get_sample(self, name: str) -> MetricSample | None:
        """Like get(), but returns the full MetricSample (including labels).

        Args:
            name: The name of the metric to fetch the sample from.
        """
        for sample in await self.fetch():
            if sample.name == name:
                return sample

        logger.debug(f"metric '{name}' not found at {self.url}")
        return None

    async def get_samples(self, names: list[str]) -> dict[str, MetricSample | None]:
        """Return all samples for a metric name across all label sets.

        Useful for metrics that appear multiple times with different labels,
        e.g. per-peer counters or histogram buckets.

        Args:
            name: The name of the metric to fetch the value from.
        """
        result: dict[str, MetricSample | None] = dict.fromkeys(names, None)
        for sample in await self.fetch():
            if sample.name in names:
                result[sample.name] = sample

        return result


class EkgError(Exception):
    """Raised when the Prometheus endpoint cannot be reached or returns an error."""
