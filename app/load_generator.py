"""Generate a steady mix of storefront reads and orders from the branch LAN."""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

BASE_URL = os.getenv("STORE_URL", "http://loja.cafeplanalto.lab")
REQUESTS_PER_SECOND = float(os.getenv("REQUESTS_PER_SECOND", "8"))


def request(path: str, payload: dict[str, int] | None = None) -> tuple[int | None, str]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json", "X-Trace-ID": os.urandom(16).hex()}
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read(512).decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(512).decode(errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, str(exc)


def main() -> None:
    if not 5 <= REQUESTS_PER_SECOND <= 20:
        raise ValueError("REQUESTS_PER_SECOND deve estar entre 5 e 20")
    interval = 1 / REQUESTS_PER_SECOND
    while True:
        started = time.monotonic()
        if random.random() < 0.75:
            status, detail = request("/produtos")
            operation = "catalogo"
        else:
            status, detail = request(
                "/pedidos",
                {"produto_id": random.randint(1, 3), "quantidade": random.randint(1, 2)},
            )
            operation = "pedido"
        print(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "nivel": "INFO" if status is not None and status < 500 else "ERROR",
                    "rota": operation,
                    "status": status,
                    **({"erro": detail} if status is None else {}),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        time.sleep(max(0, interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
