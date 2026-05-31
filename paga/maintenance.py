"""Operator CLI for encrypted-store maintenance tasks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from paga.storage import EncryptedProfileStore


def _store_from_env() -> EncryptedProfileStore:
    encryption_key = os.getenv("PAGA_ENCRYPTION_KEY")
    if not encryption_key:
        raise ValueError("PAGA_ENCRYPTION_KEY is required.")
    database_path = os.getenv("PAGA_DATABASE_PATH", "paga_profiles.sqlite3")
    if database_path != ":memory:" and not Path(database_path).is_file():
        raise ValueError(f"Encrypted store does not exist: {database_path}")
    return EncryptedProfileStore(
        database_path,
        encryption_key,
        decryption_keys=tuple(filter(None, os.getenv("PAGA_DECRYPTION_KEYS", "").split(","))),
        retention_days=int(os.getenv("PAGA_RETENTION_DAYS", "30")),
    )


def _write(payload: dict) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain the encrypted paga-eval SQLite store.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Verify SQLite structure and encrypted-record decryptability.")

    backup = commands.add_parser("backup", help="Create an online encrypted SQLite backup.")
    backup.add_argument("--output", required=True, type=Path, help="Destination SQLite backup path.")
    backup.add_argument("--overwrite", action="store_true", help="Replace an existing backup atomically.")

    commands.add_parser("prune", help="Apply configured retention to every tenant.")
    commands.add_parser("rotate-encryption", help="Re-encrypt records with the primary configured key.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = _store_from_env()
        if args.command == "check":
            profiles, audits = store.verify_integrity()
            _write({"status": "ok", "stored_audits": audits, "stored_profiles": profiles})
        elif args.command == "backup":
            output = store.backup_to(args.output, overwrite=args.overwrite)
            profiles, audits = store.verify_integrity()
            _write(
                {
                    "backup_path": str(output),
                    "status": "ok",
                    "stored_audits": audits,
                    "stored_profiles": profiles,
                }
            )
        elif args.command == "prune":
            _write(
                {
                    "status": "ok",
                    "stored_audits_deleted": store.prune_expired_audits(),
                    "stored_profiles_deleted": store.prune_expired(),
                }
            )
        elif args.command == "rotate-encryption":
            profiles, audits = store.rotate_encryption()
            store.verify_integrity()
            _write({"rotated_audits": audits, "rotated_profiles": profiles, "status": "ok"})
    except (OSError, ValueError) as error:
        print(f"maintenance failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
