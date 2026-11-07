"""Client HTTP « poli » : respecte robots.txt, espace les requêtes par site,
et s'arrête net si un site refuse (403/429/captcha) au lieu d'insister."""
from __future__ import annotations

import random
import re
import threading
import time
from urllib.parse import urlsplit

import httpx

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


class Blocked(Exception):
    """Le site refuse les requêtes automatiques : on laisse tomber pour ce cycle."""


class Disallowed(Exception):
    """robots.txt interdit cette page."""


class Robots:
    def __init__(self, text: str):
        self.rules: list[tuple[bool, re.Pattern, int]] = []
        active = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                active = v == "*"
            elif active and k in ("allow", "disallow") and v:
                rx = re.escape(v).replace(r"\*", ".*")
                if rx.endswith(r"\$"):
                    rx = rx[:-2] + "$"
                self.rules.append((k == "allow", re.compile(rx), len(v)))

    def allowed(self, path: str) -> bool:
        best = None
        for allow, rx, ln in self.rules:
            if rx.match(path) and (best is None or ln > best[1] or (ln == best[1] and allow)):
                best = (allow, ln)
        return True if best is None else best[0]


class Fetcher:
    def __init__(self, min_delay: float = 6.0, log=print):
        self.client = httpx.Client(
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
            },
            follow_redirects=True,
            timeout=30,
        )
        self.min_delay = min_delay
        self.last: dict[str, float] = {}
        self.robots: dict[str, Robots] = {}
        self.lock = threading.Lock()
        self.log = log
        self.count = 0

    def _robots(self, host: str) -> Robots:
        if host not in self.robots:
            try:
                r = self.client.get(f"https://{host}/robots.txt", timeout=15)
                self.robots[host] = Robots(r.text if r.status_code == 200 else "")
            except httpx.HTTPError:
                self.robots[host] = Robots("")
        return self.robots[host]

    def _wait(self, host: str):
        with self.lock:
            delay = self.min_delay * random.uniform(0.8, 1.6)
            nxt = self.last.get(host, 0) + delay
            now = time.time()
            if nxt > now:
                time.sleep(nxt - now)
            self.last[host] = time.time()

    def get(self, url: str) -> str:
        parts = urlsplit(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        if not self._robots(parts.netloc).allowed(path):
            raise Disallowed(url)
        self._wait(parts.netloc)
        try:
            r = self.client.get(url)
        except httpx.HTTPError as e:
            raise Blocked(f"réseau : {e}") from e
        self.count += 1
        body = r.text
        if r.status_code in (403, 429, 503) or (r.status_code == 202 and len(body) < 10000):
            raise Blocked(f"HTTP {r.status_code}")
        if re.search(r"captcha|validateCaptcha|Robot Check|api-services-support@amazon", body[:20000], re.I) and len(body) < 60000:
            raise Blocked("captcha")
        if r.status_code == 404:
            raise Blocked("page introuvable (404) — le site a peut-être changé")
        r.raise_for_status()
        return body
