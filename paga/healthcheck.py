"""Container-native readiness probe using only the Python standard library."""

from __future__ import annotations

import json
import os
from urllib.request import urlopen


def main() -> None:
    url = os.getenv("PAGA_HEALTHCHECK_URL", "http://127.0.0.1:8000/readyz")
    with urlopen(url, timeout=2) as response:
        payload = json.load(response)
    if response.status != 200 or payload != {"status": "ready"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
