"""Install explicit routes in a Compose service's network namespace."""

from __future__ import annotations

import ipaddress
import subprocess
import sys
import time


def main(arguments: list[str]) -> int:
    if len(arguments) < 3 or len(arguments) % 2 == 0:
        print("usage: route-init <network> <gateway> [<network> <gateway> ...]", file=sys.stderr)
        return 2
    try:
        routes = [
            (ipaddress.ip_network(arguments[index]), ipaddress.ip_address(arguments[index + 1]))
            for index in range(1, len(arguments), 2)
        ]
    except ValueError as exc:
        print(f"invalid route: {exc}", file=sys.stderr)
        return 2

    last_error: subprocess.CalledProcessError | None = None
    for _ in range(30):
        try:
            for network, gateway in routes:
                subprocess.run(
                    ["ip", "route", "replace", str(network), "via", str(gateway)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            return 0
        except subprocess.CalledProcessError as exc:
            last_error = exc
            time.sleep(1)
    if last_error is not None:
        print(last_error.stderr.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
