"""Encrypted profile storage tests."""

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from paga.storage import EncryptedProfileStore


def test_store_encrypts_round_trips_and_deletes_profile(tmp_path):
    database = tmp_path / "profiles.sqlite3"
    store = EncryptedProfileStore(database, EncryptedProfileStore.generate_key())
    profile = {"user_id": "learner_123", "total_attempts": 2}
    store.put("learner_123", profile)

    with sqlite3.connect(database) as connection:
        encrypted = connection.execute("SELECT encrypted_profile FROM learner_profiles").fetchone()[0]
    assert b"total_attempts" not in encrypted
    assert store.get("learner_123") == profile
    assert store.delete("learner_123") is True
    assert store.get("learner_123") is None


def test_store_prunes_expired_profiles(tmp_path):
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    store = EncryptedProfileStore(
        tmp_path / "profiles.sqlite3",
        EncryptedProfileStore.generate_key(),
        retention_days=30,
        clock=lambda: now[0],
    )
    store.put("learner_expiring", {"user_id": "learner_expiring"})
    now[0] += timedelta(days=31)
    assert store.prune_expired() == 1
    assert store.count() == 0


def test_store_rejects_raw_learner_identifier(tmp_path):
    store = EncryptedProfileStore(tmp_path / "profiles.sqlite3", EncryptedProfileStore.generate_key())
    with pytest.raises(ValueError, match="pseudonymous"):
        store.put("student-123", {"user_id": "student-123"})


def test_store_encrypts_and_prunes_append_only_audits(tmp_path):
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    database = tmp_path / "profiles.sqlite3"
    store = EncryptedProfileStore(
        database,
        EncryptedProfileStore.generate_key(),
        retention_days=30,
        clock=lambda: now[0],
    )
    store.append_audit({"evaluation_id": "eval-1", "target": "", "verdict": "PASS"})
    with sqlite3.connect(database) as connection:
        encrypted = connection.execute("SELECT encrypted_audit FROM evaluation_audits").fetchone()[0]
    assert b"verdict" not in encrypted
    with pytest.raises(ValueError, match="already exists"):
        store.append_audit({"evaluation_id": "eval-1"})
    now[0] += timedelta(days=31)
    assert store.prune_expired_audits() == 1
    assert store.count_audits() == 0


def test_store_rotates_encryption_key(tmp_path):
    database = tmp_path / "profiles.sqlite3"
    old_key = EncryptedProfileStore.generate_key()
    new_key = EncryptedProfileStore.generate_key()
    old_store = EncryptedProfileStore(database, old_key)
    old_store.put("learner_rotate", {"user_id": "learner_rotate"})
    old_store.append_audit({"evaluation_id": "eval-rotate"})
    rotating_store = EncryptedProfileStore(database, new_key, decryption_keys=(old_key,))
    assert rotating_store.rotate_encryption() == (1, 1)
    assert rotating_store.get("learner_rotate") == {"user_id": "learner_rotate"}
    new_only_store = EncryptedProfileStore(database, new_key)
    assert new_only_store.get("learner_rotate") == {"user_id": "learner_rotate"}


def test_store_scopes_profiles_and_replay_ids_by_tenant(tmp_path):
    store = EncryptedProfileStore(tmp_path / "profiles.sqlite3", EncryptedProfileStore.generate_key())
    store.put("learner_tenant_a", {"user_id": "learner_tenant_a"}, tenant_id="district-a")
    assert store.get("learner_tenant_a", tenant_id="district-b") is None
    store.append_audit({"evaluation_id": "same-id"}, tenant_id="district-a")
    store.append_audit({"evaluation_id": "same-id"}, tenant_id="district-b")
    assert store.count(tenant_id="district-a") == 1
    assert store.count(tenant_id="district-b") == 0
    assert store.count_audits(tenant_id="district-a") == 1
    assert store.count_audits(tenant_id="district-b") == 1


def test_store_does_not_transfer_profile_ownership_when_tenants_reuse_profile_id(tmp_path):
    store = EncryptedProfileStore(tmp_path / "profiles.sqlite3", EncryptedProfileStore.generate_key())
    store.put("learner_shared", {"user_id": "learner_shared", "marker": "a"}, tenant_id="district-a")
    store.put("learner_shared", {"user_id": "learner_shared", "marker": "b"}, tenant_id="district-b")
    assert store.get("learner_shared", tenant_id="district-a")["marker"] == "a"
    assert store.get("learner_shared", tenant_id="district-b")["marker"] == "b"


def test_store_migrates_pre_tenant_schema(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE learner_profiles (profile_id TEXT PRIMARY KEY, encrypted_profile BLOB NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE evaluation_audits (evaluation_id TEXT PRIMARY KEY, encrypted_audit BLOB NOT NULL, created_at TEXT NOT NULL)"
        )
    store = EncryptedProfileStore(database, EncryptedProfileStore.generate_key())
    with sqlite3.connect(database) as connection:
        profile_columns = {row[1] for row in connection.execute("PRAGMA table_info(learner_profiles)")}
        audit_columns = {row[1] for row in connection.execute("PRAGMA table_info(evaluation_audits)")}
    assert "tenant_id" in profile_columns
    assert "tenant_id" in audit_columns


def test_store_verifies_integrity_and_creates_readable_online_backup(tmp_path):
    database = tmp_path / "profiles.sqlite3"
    backup = tmp_path / "backups" / "profiles.sqlite3"
    key = EncryptedProfileStore.generate_key()
    store = EncryptedProfileStore(database, key)
    store.put("learner_backup", {"user_id": "learner_backup"})
    store.append_audit({"evaluation_id": "eval-backup"})

    assert store.verify_integrity() == (1, 1)
    assert store.backup_to(backup) == backup.resolve()
    restored = EncryptedProfileStore(backup, key)
    assert restored.verify_integrity() == (1, 1)
    assert restored.get("learner_backup") == {"user_id": "learner_backup"}

    with pytest.raises(FileExistsError, match="already exists"):
        store.backup_to(backup)
    assert store.backup_to(backup, overwrite=True) == backup.resolve()


def test_store_integrity_verification_rejects_corrupted_ciphertext(tmp_path):
    database = tmp_path / "profiles.sqlite3"
    store = EncryptedProfileStore(database, EncryptedProfileStore.generate_key())
    store.put("learner_corrupt", {"user_id": "learner_corrupt"})
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE learner_profiles SET encrypted_profile = ? WHERE profile_id = ?",
            (b"not-valid-ciphertext", "learner_corrupt"),
        )
    with pytest.raises(ValueError, match="integrity verification"):
        store.verify_integrity()
