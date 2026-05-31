"""Launch the local institution demo with non-production credentials."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import gettempdir

import uvicorn

from institution_demo_app import create_demo_app

DEMO_API_KEY = "local-demo-api-key-at-least-24"


def configure_local_demo() -> None:
    """Set local-only defaults without overriding operator-provided values."""

    os.environ.setdefault("PAGA_API_KEY", DEMO_API_KEY)
    os.environ.setdefault("PAGA_PROFILE_SALT", "local-demo-profile-salt-at-least-24")
    os.environ.setdefault("PAGA_ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    os.environ.setdefault("PAGA_DATABASE_PATH", str(Path(gettempdir()) / "paga-eval-demo.sqlite3"))


if __name__ == "__main__":
    configure_local_demo()
    uvicorn.run(create_demo_app(), host="127.0.0.1", port=int(os.getenv("PAGA_DEMO_PORT", "8000")))
