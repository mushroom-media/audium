"""API latency test against a running instance: `audium loadtest --user .. --password ..`.

Mixes the requests a browsing UI makes (sequential cursor pages, scrollbar jumps via offset,
detail views, search-as-you-type prefixes) and reports p50/p95/p99 per request type.
Stdlib only, so it also runs inside the production image.
"""

import json
import random
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cookie = ""

    def request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("X-Requested-With", "audium-loadtest")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - user-supplied test target
            payload = resp.read()
            for header in resp.headers.get_all("Set-Cookie") or []:
                if header.startswith("audium_session="):
                    self.cookie = header.split(";", 1)[0]
            return json.loads(payload) if payload else None

    def get(self, path: str, **params):
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return self.request("GET", f"{path}?{query}" if query else path)


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = min(len(values) - 1, max(0, round(p / 100 * (len(values) - 1))))
    return values[k]


def run(url: str, user: str, password: str, n_requests: int, concurrency: int, search_p95_ms: float) -> int:
    client = Client(url)
    client.request("POST", "/api/v1/auth/login", {"username": user, "password": password})
    api = "/api/v1"
    tracks_total = client.get(f"{api}/tracks", limit=1)["total"]
    albums_total = client.get(f"{api}/albums", limit=1)["total"]
    artists_total = client.get(f"{api}/artists", limit=1)["total"]
    if not tracks_total:
        print("library is empty; generate one first (audium gen-testlib)")
        return 1
    sample_albums = client.get(f"{api}/albums", limit=500, offset=random.randrange(max(1, albums_total - 500)))
    album_ids = [a["id"] for a in sample_albums["items"]]
    words = [w for a in sample_albums["items"] for w in (a["title"] + " " + a["artist"]).split() if len(w) >= 3]
    print(f"library: {tracks_total} tracks, {albums_total} albums, {artists_total} artists")

    rng = random.Random(7)

    def scenario():
        kind = rng.choices(
            (
                "tracks_jump",
                "tracks_next",
                "albums_jump",
                "albums_by_artist_sort",
                "artists_jump",
                "album_detail",
                "search",
            ),
            (15, 15, 15, 5, 10, 10, 30),
        )[0]
        if kind == "tracks_jump":
            return kind, lambda: client.get(f"{api}/tracks", offset=rng.randrange(tracks_total), limit=100)
        if kind == "tracks_next":
            sort = rng.choice(["title", "added"])
            start = rng.randrange(tracks_total)

            def jump_then_next():  # two requests: jump, then the following page by cursor
                page = client.get(f"{api}/tracks", sort=sort, limit=100, offset=start)
                if page["next_cursor"]:
                    client.get(f"{api}/tracks", sort=sort, limit=100, cursor=page["next_cursor"])

            return "tracks_jump+cursor(2req)", jump_then_next
        if kind == "albums_jump":
            return kind, lambda: client.get(
                f"{api}/albums",
                offset=rng.randrange(albums_total),
                limit=100,
                sort=rng.choice(["title", "year", "added"]),
            )
        if kind == "albums_by_artist_sort":
            return kind, lambda: client.get(
                f"{api}/albums", sort="artist", offset=rng.randrange(albums_total), limit=100
            )
        if kind == "artists_jump":
            return kind, lambda: client.get(f"{api}/artists", offset=rng.randrange(max(1, artists_total)), limit=100)
        if kind == "album_detail":
            return kind, lambda: client.get(f"{api}/albums/{rng.choice(album_ids)}")
        word = rng.choice(words)
        prefix = word[: rng.randint(2, len(word))]
        return kind, lambda: client.get(f"{api}/search", q=prefix, limit=20)

    def timed(item):
        kind, call = item
        start = time.perf_counter()
        try:
            call()
            ok = True
        except (urllib.error.URLError, TimeoutError, ValueError):
            ok = False
        return kind, (time.perf_counter() - start) * 1000, ok

    work = [scenario() for _ in range(n_requests)]
    latencies: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for kind, ms, ok in pool.map(timed, work):
            latencies[kind].append(ms)
            if not ok:
                errors[kind] += 1
    elapsed = time.perf_counter() - started

    print(f"\n{n_requests} requests, concurrency {concurrency}, {n_requests / elapsed:.0f} req/s\n")
    print(f"{'request':24} {'n':>6} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8} {'err':>5}")
    for kind in sorted(latencies):
        v = latencies[kind]
        print(
            f"{kind:24} {len(v):6d} {statistics.median(v):7.1f}ms {_pct(v, 95):7.1f}ms "
            f"{_pct(v, 99):7.1f}ms {max(v):7.1f}ms {errors[kind]:5d}"
        )
    search_p95 = _pct(latencies.get("search", []), 95)
    error_rate = sum(errors.values()) / max(1, n_requests)
    failed = search_p95 > search_p95_ms or error_rate > 0.01
    print(
        f"\nsearch p95 {search_p95:.1f} ms (limit {search_p95_ms:.0f} ms), errors {error_rate:.2%}: "
        f"{'FAIL' if failed else 'OK'}"
    )
    return 1 if failed else 0
