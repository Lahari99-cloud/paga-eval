"""Encrypted SQLite storage for privacy-safe learner profiles."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping
from uuid import uuid4

try:
    from cryptography.fernet import Fernet, InvalidToken, MultiFernet
except ImportError as error:  # pragma: no cover - exercised in minimal installs
    raise ImportError("EncryptedProfileStore requires: pip install 'paga-eval[service]'") from error


class EncryptedProfileStore:
    """Persist JSON profiles encrypted at rest with retention enforcement.

    The caller supplies a stable pseudonymous profile ID. Raw learner identifiers
    must not be used as storage keys.
    """

    def __init__(
        self,
        database_path: str | Path,
        encryption_key: str | bytes,
        *,
        decryption_keys: Iterable[str | bytes] = (),
        retention_days: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1.")
        self.database_path = str(database_path)
        self.retention_days = retention_days
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cipher = MultiFernet([Fernet(encryption_key), *(Fernet(key) for key in decryption_keys)])
        self._initialize()

    @staticmethod
    def generate_key() -> str:
        """Generate a Fernet key suitable for a deployment secrets manager."""

        return Fernet.generate_key().decode()

    def put(self, profile_id: str, profile: Mapping[str, object], *, tenant_id: str = "default") -> None:
        """Encrypt and upsert one pseudonymous learner profile."""

        self._validate_profile_id(profile_id)
        self._validate_tenant_id(tenant_id)
        if profile.get("user_id") not in {None, profile_id}:
            raise ValueError("Stored profile user_id must match the pseudonymous profile_id.")
        payload = json.dumps(dict(profile), separators=(",", ":"), sort_keys=True).encode()
        encrypted = self.cipher.encrypt(payload)
        updated_at = self.clock().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO learner_profiles(profile_id, encrypted_profile, updated_at, tenant_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_id, tenant_id) DO UPDATE SET
                    encrypted_profile = excluded.encrypted_profile,
                    updated_at = excluded.updated_at
                """,
                (profile_id, encrypted, updated_at, tenant_id),
            )

    def get(self, profile_id: str, *, tenant_id: str = "default") -> dict | None:
        """Decrypt one profile if it exists and has not expired."""

        self._validate_profile_id(profile_id)
        self._validate_tenant_id(tenant_id)
        self.prune_expired(tenant_id=tenant_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_profile FROM learner_profiles WHERE profile_id = ? AND tenant_id = ?",
                (profile_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(self.cipher.decrypt(row[0]))
        except InvalidToken as error:
            raise ValueError("Stored profile could not be decrypted with the configured key.") from error

    def delete(self, profile_id: str, *, tenant_id: str = "default") -> bool:
        """Delete one profile and report whether a row existed."""

        self._validate_profile_id(profile_id)
        self._validate_tenant_id(tenant_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM learner_profiles WHERE profile_id = ? AND tenant_id = ?",
                (profile_id, tenant_id),
            )
        return cursor.rowcount > 0

    def prune_expired(self, *, tenant_id: str | None = None) -> int:
        """Delete profiles older than the configured retention period."""

        cutoff = (self.clock() - timedelta(days=self.retention_days)).isoformat()
        with self._connect() as connection:
            if tenant_id is None:
                cursor = connection.execute("DELETE FROM learner_profiles WHERE updated_at < ?", (cutoff,))
            else:
                self._validate_tenant_id(tenant_id)
                cursor = connection.execute(
                    "DELETE FROM learner_profiles WHERE updated_at < ? AND tenant_id = ?",
                    (cutoff, tenant_id),
                )
        return cursor.rowcount

    def prune_expired_audits(self, *, tenant_id: str | None = None) -> int:
        """Delete audit records older than the configured retention period."""

        cutoff = (self.clock() - timedelta(days=self.retention_days)).isoformat()
        with self._connect() as connection:
            if tenant_id is None:
                cursor = connection.execute("DELETE FROM evaluation_audits WHERE created_at < ?", (cutoff,))
            else:
                self._validate_tenant_id(tenant_id)
                cursor = connection.execute(
                    "DELETE FROM evaluation_audits WHERE created_at < ? AND tenant_id = ?",
                    (cutoff, tenant_id),
                )
        return cursor.rowcount

    def count(self, *, tenant_id: str | None = None) -> int:
        """Return the number of encrypted records, primarily for operations."""

        with self._connect() as connection:
            if tenant_id is None:
                return connection.execute("SELECT COUNT(*) FROM learner_profiles").fetchone()[0]
            self._validate_tenant_id(tenant_id)
            return connection.execute(
                "SELECT COUNT(*) FROM learner_profiles WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()[0]

    def readiness_check(self) -> None:
        """Raise if the configured database is unavailable."""

        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def verify_integrity(self) -> tuple[int, int]:
        """Verify SQLite structure and decryptability of every stored record."""

        with self._connect() as connection:
            self._assert_sqlite_integrity(connection)
            profiles = connection.execute("SELECT encrypted_profile FROM learner_profiles").fetchall()
            audits = connection.execute("SELECT encrypted_audit FROM evaluation_audits").fetchall()
        try:
            for (payload,) in (*profiles, *audits):
                json.loads(self.cipher.decrypt(payload))
        except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Stored encrypted data failed integrity verification.") from error
        return len(profiles), len(audits)

    def backup_to(self, destination: str | Path, *, overwrite: bool = False) -> Path:
        """Create an atomically published online SQLite backup."""

        destination = Path(destination).resolve()
        source = None if self.database_path == ":memory:" else Path(self.database_path).resolve()
        if source == destination:
            raise ValueError("Backup destination must differ from the active database.")
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Backup destination already exists: {destination}")

        self.verify_integrity()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            with self._connect() as source_connection, closing(sqlite3.connect(temporary)) as backup_connection:
                source_connection.backup(backup_connection)
                self._assert_sqlite_integrity(backup_connection)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def append_audit(self, audit_record: Mapping[str, object], *, tenant_id: str = "default") -> None:
        """Encrypt and append one immutable evaluator audit record."""

        self.append_audits((audit_record,), tenant_id=tenant_id)

    def append_audits(self, audit_records: Iterable[Mapping[str, object]], *, tenant_id: str = "default") -> None:
        """Encrypt and append audit records atomically."""

        self._validate_tenant_id(tenant_id)
        rows = []
        for audit_record in audit_records:
            evaluation_id = str(audit_record.get("evaluation_id", ""))
            if not evaluation_id or len(evaluation_id) > 128:
                raise ValueError("Audit records require a bounded evaluation_id.")
            storage_id = f"{tenant_id}:{evaluation_id}"
            payload = json.dumps(
                {**dict(audit_record), "tenant_id": tenant_id},
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            rows.append((storage_id, self.cipher.encrypt(payload), self.clock().isoformat(), tenant_id))
        try:
            with self._connect() as connection:
                connection.executemany(
                    """
                    INSERT INTO evaluation_audits(evaluation_id, encrypted_audit, created_at, tenant_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    rows,
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("Audit evaluation_id already exists.") from error

    def count_audits(self, *, tenant_id: str | None = None) -> int:
        """Return persisted audit count for operational monitoring."""

        with self._connect() as connection:
            if tenant_id is None:
                return connection.execute("SELECT COUNT(*) FROM evaluation_audits").fetchone()[0]
            self._validate_tenant_id(tenant_id)
            return connection.execute(
                "SELECT COUNT(*) FROM evaluation_audits WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()[0]

    def rotate_encryption(self) -> tuple[int, int]:
        """Re-encrypt all records with the primary key and return rotated counts."""

        with self._connect() as connection:
            profiles = connection.execute("SELECT profile_id, encrypted_profile FROM learner_profiles").fetchall()
            audits = connection.execute("SELECT evaluation_id, encrypted_audit FROM evaluation_audits").fetchall()
            connection.executemany(
                "UPDATE learner_profiles SET encrypted_profile = ? WHERE profile_id = ?",
                ((self.cipher.rotate(payload), profile_id) for profile_id, payload in profiles),
            )
            connection.executemany(
                "UPDATE evaluation_audits SET encrypted_audit = ? WHERE evaluation_id = ?",
                ((self.cipher.rotate(payload), evaluation_id) for evaluation_id, payload in audits),
            )
        return len(profiles), len(audits)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS learner_profiles (
                    profile_id TEXT NOT NULL,
                    encrypted_profile BLOB NOT NULL,
                    updated_at TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    PRIMARY KEY(profile_id, tenant_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_audits (
                    evaluation_id TEXT PRIMARY KEY,
                    encrypted_audit BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    tenant_id TEXT NOT NULL DEFAULT 'default'
                )
                """
            )
            self._ensure_column(connection, "learner_profiles", "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
            self._ensure_column(connection, "evaluation_audits", "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
            self._migrate_profile_tenant_primary_key(connection)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_profile_id(profile_id: str) -> None:
        if not profile_id.startswith("learner_") or len(profile_id) > 128:
            raise ValueError("Storage keys must be bounded pseudonymous learner IDs.")

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        if not tenant_id or len(tenant_id) > 64 or not all(char.isalnum() or char in "._-" for char in tenant_id):
            raise ValueError("tenant_id must contain only letters, numbers, dots, underscores, or hyphens.")

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _migrate_profile_tenant_primary_key(connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(learner_profiles)").fetchall()
        primary_key = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        if primary_key == ["profile_id", "tenant_id"]:
            return
        connection.execute("ALTER TABLE learner_profiles RENAME TO learner_profiles_legacy")
        connection.execute(
            """
            CREATE TABLE learner_profiles (
                profile_id TEXT NOT NULL,
                encrypted_profile BLOB NOT NULL,
                updated_at TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                PRIMARY KEY(profile_id, tenant_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO learner_profiles(profile_id, encrypted_profile, updated_at, tenant_id)
            SELECT profile_id, encrypted_profile, updated_at, tenant_id
            FROM learner_profiles_legacy
            """
        )
        connection.execute("DROP TABLE learner_profiles_legacy")

    @staticmethod
    def _assert_sqlite_integrity(connection: sqlite3.Connection) -> None:
        results = connection.execute("PRAGMA integrity_check").fetchall()
        if results != [("ok",)]:
            raise ValueError("SQLite integrity verification failed.")
