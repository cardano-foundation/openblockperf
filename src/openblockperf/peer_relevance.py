"""Sliding-window peer relevance from header/body observations.

Fixed 30-minute window (not configurable) for comparable metrics across clients.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

HEADER_POINTS = {1: 10, 2: 5, 3: 3}
BODY_POINTS = 10
RELEVANCE_WINDOW = timedelta(minutes=30)
RELEVANCE_REPORT_INTERVAL_SECONDS = 30 * 60


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Contribution:
    at: datetime
    kind: str  # header_1 | header_2 | header_3 | body
    points: int


@dataclass
class PeerRelevanceScore:
    remote_addr: str
    headers_1st_count: int = 0
    headers_2nd_count: int = 0
    headers_3rd_count: int = 0
    header_points: int = 0
    bodies_count: int = 0
    body_points: int = 0

    @property
    def headers_count(self) -> int:
        return self.headers_1st_count + self.headers_2nd_count + self.headers_3rd_count


@dataclass
class PeerRelevanceTracker:
    """Accumulates scored header/body events and expires them after 30 minutes."""

    window: timedelta = RELEVANCE_WINDOW
    _by_ip: dict[str, list[_Contribution]] = field(default_factory=dict)

    def record_header(self, remote_addr: str, rank: int, at: datetime) -> int:
        """Record a 1st/2nd/3rd header announcer. Returns points awarded (0 if ignored)."""
        points = HEADER_POINTS.get(rank, 0)
        if not points:
            return 0
        kind = f"header_{rank}"
        self._add(remote_addr, _Contribution(at=_as_aware(at), kind=kind, points=points))
        return points

    def record_body(self, remote_addr: str, at: datetime) -> int:
        """Record first body server for a block. Returns points awarded."""
        self._add(
            remote_addr,
            _Contribution(at=_as_aware(at), kind="body", points=BODY_POINTS),
        )
        return BODY_POINTS

    def _add(self, remote_addr: str, contrib: _Contribution) -> None:
        self._by_ip.setdefault(remote_addr, []).append(contrib)

    def _prune_ip(self, remote_addr: str, now: datetime) -> None:
        cutoff = now - self.window
        items = self._by_ip.get(remote_addr)
        if not items:
            return
        kept = [c for c in items if c.at >= cutoff]
        if kept:
            self._by_ip[remote_addr] = kept
        else:
            self._by_ip.pop(remote_addr, None)

    def prune(self, now: datetime | None = None) -> None:
        now = _as_aware(now or _now())
        for ip in list(self._by_ip):
            self._prune_ip(ip, now)

    def score_for(self, remote_addr: str, now: datetime | None = None) -> PeerRelevanceScore:
        now = _as_aware(now or _now())
        self._prune_ip(remote_addr, now)
        score = PeerRelevanceScore(remote_addr=remote_addr)
        for c in self._by_ip.get(remote_addr, []):
            if c.kind == "header_1":
                score.headers_1st_count += 1
                score.header_points += c.points
            elif c.kind == "header_2":
                score.headers_2nd_count += 1
                score.header_points += c.points
            elif c.kind == "header_3":
                score.headers_3rd_count += 1
                score.header_points += c.points
            elif c.kind == "body":
                score.bodies_count += 1
                score.body_points += c.points
        return score

    def all_scores(self, now: datetime | None = None) -> list[PeerRelevanceScore]:
        now = _as_aware(now or _now())
        self.prune(now)
        scores = [self.score_for(ip, now) for ip in self._by_ip]
        scores.sort(key=lambda s: (-(s.header_points + s.body_points), s.remote_addr))
        return scores

    def score_dict(self, remote_addr: str, now: datetime | None = None) -> dict:
        s = self.score_for(remote_addr, now)
        return {
            "headers_count": s.headers_count,
            "headers_1st_count": s.headers_1st_count,
            "headers_2nd_count": s.headers_2nd_count,
            "headers_3rd_count": s.headers_3rd_count,
            "header_points": s.header_points,
            "bodies_count": s.bodies_count,
            "body_points": s.body_points,
        }

    def snapshot(self, now: datetime | None = None) -> dict:
        """Local snapshot shape for journal / /peers; not submitted upstream."""
        now = _as_aware(now or _now())
        peers = []
        for s in self.all_scores(now):
            peers.append(
                {
                    "remote_addr": s.remote_addr,
                    "headers_count": s.headers_count,
                    "headers_1st_count": s.headers_1st_count,
                    "headers_2nd_count": s.headers_2nd_count,
                    "headers_3rd_count": s.headers_3rd_count,
                    "header_points": s.header_points,
                    "bodies_count": s.bodies_count,
                    "body_points": s.body_points,
                }
            )
        return {
            "kind": "peerRelevanceSnapshot",
            "at": now.isoformat(),
            "window_seconds": int(self.window.total_seconds()),
            "peers": peers,
        }
