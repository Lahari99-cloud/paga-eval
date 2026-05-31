"""Run the optional institutional API from environment-based settings."""

import uvicorn

from paga.api import create_app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
