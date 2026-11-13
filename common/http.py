"""Cliente HTTP con pausa de 1–2 s entre peticiones, user-agent normal y reintentos."""
import logging
import random
import time

import requests

from .config import load_config

log = logging.getLogger(__name__)


class Http:
    def __init__(self, cfg: dict | None = None):
        c = (cfg or load_config())["http"]
        self.pmin, self.pmax = c["pausa_min_s"], c["pausa_max_s"]
        self.timeout = c["timeout_s"]
        self.retries = c["reintentos"]
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": c["user_agent"],
            "Accept-Language": "es-CO,es;q=0.9",
        })
        self._last = 0.0

    def _wait(self):
        pause = random.uniform(self.pmin, self.pmax)
        dt = time.monotonic() - self._last
        if dt < pause:
            time.sleep(pause - dt)

    def request(self, method: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        err = None
        for intento in range(1, self.retries + 1):
            self._wait()
            try:
                r = self.s.request(method, url, **kw)
                self._last = time.monotonic()
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                self._last = time.monotonic()
                err = e
                log.warning("Intento %d/%d falló %s: %s", intento, self.retries, url, e)
                time.sleep(2 * intento)
        raise err

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
