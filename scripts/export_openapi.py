"""Export the hosted-service OpenAPI contract deterministically."""

from __future__ import annotations

import json
from pathlib import Path

from paga.api import ServiceSettings, create_app
from paga.storage import EncryptedProfileStore


def main() -> None:
    settings = ServiceSettings(
        api_key="openapi-contract-key-at-least-24",
        profile_salt="openapi-profile-salt-at-least-24",
        encryption_key=EncryptedProfileStore.generate_key(),
        database_path=":memory:",
    )
    contract = json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n"
    Path("openapi.json").write_text(contract, encoding="ascii")


if __name__ == "__main__":
    main()
