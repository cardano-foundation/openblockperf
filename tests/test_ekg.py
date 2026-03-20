"""Tests for openblockperf.prometheus

The parser (``parse`` / ``_parse_line``) is pure and sync — no extra deps.
The async ``EkgClient`` tests require::

    uv add --dev pytest-asyncio respx

and the following in pyproject.toml::

    [tool.pytest.ini_options]
    asyncio_mode = "auto"
"""

import pytest

from openblockperf.prometheus import MetricSample, EkgClient, EkgError, parse

# ---------------------------------------------------------------------------
# Fixtures — sample Prometheus text bodies
# ---------------------------------------------------------------------------

SIMPLE_BODY = """\
# HELP cardano_node_metrics_blockNum_int Current block number
# TYPE cardano_node_metrics_blockNum_int gauge
cardano_node_metrics_blockNum_int 11653581
# HELP cardano_node_metrics_txsInMempool_int Transactions in mempool
# TYPE cardano_node_metrics_txsInMempool_int gauge
cardano_node_metrics_txsInMempool_int 4
"""

LABELLED_BODY = """\
# HELP rts_gc_num_gcs Number of GCs performed
# TYPE rts_gc_num_gcs counter
rts_gc_num_gcs{generation="0"} 12345
rts_gc_num_gcs{generation="1"} 67
"""

EDGE_CASE_BODY = """\
# HELP some_metric A metric
some_inf_metric +Inf
some_neg_inf_metric -Inf
some_nan_metric NaN
some_float_metric 3.14e2
some_zero_metric 0
"""


# ---------------------------------------------------------------------------
# Parser unit tests (sync, no external deps)
# ---------------------------------------------------------------------------


class TestParse:
    def test_returns_list_of_metric_samples(self):
        samples = parse(SIMPLE_BODY)
        assert all(isinstance(s, MetricSample) for s in samples)

    def test_skips_comment_lines(self):
        samples = parse(SIMPLE_BODY)
        names = [s.name for s in samples]
        assert not any(n.startswith("#") for n in names)

    def test_correct_number_of_samples(self):
        assert len(parse(SIMPLE_BODY)) == 2

    def test_empty_string_returns_empty_list(self):
        assert parse("") == []

    def test_only_comments_returns_empty_list(self):
        assert parse("# HELP foo bar\n# TYPE foo gauge\n") == []

    def test_blank_lines_are_ignored(self):
        assert parse("\n\n\n") == []


class TestParseSample:
    def test_name_parsed(self):
        samples = parse(SIMPLE_BODY)
        assert samples[0].name == "cardano_node_metrics_blockNum_int"

    def test_value_parsed_as_float(self):
        samples = parse(SIMPLE_BODY)
        assert samples[0].value == 11653581.0

    def test_no_labels_gives_empty_dict(self):
        samples = parse(SIMPLE_BODY)
        assert samples[0].labels == {}

    def test_labelled_metric_name(self):
        samples = parse(LABELLED_BODY)
        assert samples[0].name == "rts_gc_num_gcs"

    def test_labels_parsed(self):
        samples = parse(LABELLED_BODY)
        assert samples[0].labels == {"generation": "0"}
        assert samples[1].labels == {"generation": "1"}

    def test_multiple_labels(self):
        text = 'http_requests_total{method="GET",code="200"} 1027\n'
        samples = parse(text)
        assert samples[0].labels == {"method": "GET", "code": "200"}


class TestParseEdgeCases:
    def test_positive_infinity(self):
        samples = parse("some_inf_metric +Inf\n")
        import math
        assert math.isinf(samples[0].value) and samples[0].value > 0

    def test_negative_infinity(self):
        samples = parse("some_neg_inf_metric -Inf\n")
        import math
        assert math.isinf(samples[0].value) and samples[0].value < 0

    def test_nan(self):
        samples = parse("some_nan_metric NaN\n")
        import math
        assert math.isnan(samples[0].value)

    def test_scientific_notation(self):
        samples = parse("some_float_metric 3.14e2\n")
        assert samples[0].value == pytest.approx(314.0)

    def test_zero(self):
        samples = parse("some_zero_metric 0\n")
        assert samples[0].value == 0.0

    def test_malformed_line_returns_no_sample(self):
        # A line with no value should produce zero samples
        samples = parse("this_is_not_valid\n")
        assert samples == []

    # TODO: metric with timestamp suffix (3rd column) — should still parse


# ---------------------------------------------------------------------------
# EkgClient async tests
#
# These require:  uv add --dev pytest-asyncio respx
# Uncomment and add  asyncio_mode = "auto"  to [tool.pytest.ini_options]
# ---------------------------------------------------------------------------

# import respx, httpx
#
# pytestmark = pytest.mark.asyncio
#
#
# @pytest.fixture
# def client():
#     return EkgClient("http://localhost:12798/metrics")
#
#
# async def test_fetch_returns_samples(client):
#     with respx.mock:
#         respx.get("http://localhost:12798/metrics").mock(
#             return_value=httpx.Response(200, text=SIMPLE_BODY)
#         )
#         samples = await client.fetch()
#     assert len(samples) == 2
#
#
# async def test_get_returns_correct_value(client):
#     with respx.mock:
#         respx.get("http://localhost:12798/metrics").mock(
#             return_value=httpx.Response(200, text=SIMPLE_BODY)
#         )
#         value = await client.get("cardano_node_metrics_blockNum_int")
#     assert value == 11653581.0
#
#
# async def test_get_returns_none_for_unknown_metric(client):
#     with respx.mock:
#         respx.get("http://localhost:12798/metrics").mock(
#             return_value=httpx.Response(200, text=SIMPLE_BODY)
#         )
#         value = await client.get("metric_that_does_not_exist")
#     assert value is None
#
#
# async def test_get_many_fetches_once(client):
#     with respx.mock:
#         route = respx.get("http://localhost:12798/metrics").mock(
#             return_value=httpx.Response(200, text=SIMPLE_BODY)
#         )
#         result = await client.get_many([
#             "cardano_node_metrics_blockNum_int",
#             "cardano_node_metrics_txsInMempool_int",
#             "not_present",
#         ])
#     assert route.call_count == 1
#     assert result["cardano_node_metrics_blockNum_int"] == 11653581.0
#     assert result["cardano_node_metrics_txsInMempool_int"] == 4.0
#     assert result["not_present"] is None
#
#
# async def test_get_with_label_filter(client):
#     with respx.mock:
#         respx.get("http://localhost:12798/metrics").mock(
#             return_value=httpx.Response(200, text=LABELLED_BODY)
#         )
#         value = await client.get("rts_gc_num_gcs", labels={"generation": "1"})
#     assert value == 67.0
#
#
# async def test_http_error_raises_prometheus_error(client):
#     with respx.mock:
#         respx.get("http://localhost:12798/metrics").mock(
#             return_value=httpx.Response(503)
#         )
#         with pytest.raises(EkgError):
#             await client.fetch()
#
#
# async def test_connect_error_raises_prometheus_error(client):
#     with respx.mock:
#         respx.get("http://localhost:12798/metrics").mock(
#             side_effect=httpx.ConnectError("refused")
#         )
#         with pytest.raises(EkgError):
#             await client.fetch()
