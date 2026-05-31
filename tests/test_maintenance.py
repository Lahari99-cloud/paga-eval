"""Operator maintenance CLI tests."""

import json

from paga.maintenance import main
from paga.storage import EncryptedProfileStore


def _configure(monkeypatch, database, key, *, decryption_keys=""):
    monkeypatch.setenv("PAGA_DATABASE_PATH", str(database))
    monkeypatch.setenv("PAGA_ENCRYPTION_KEY", key)
    monkeypatch.setenv("PAGA_DECRYPTION_KEYS", decryption_keys)
    monkeypatch.setenv("PAGA_RETENTION_DAYS", "30")


def test_maintenance_cli_checks_and_backs_up_store(tmp_path, monkeypatch, capsys):
    database = tmp_path / "profiles.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    key = EncryptedProfileStore.generate_key()
    store = EncryptedProfileStore(database, key)
    store.put("learner_cli", {"user_id": "learner_cli"})
    store.append_audit({"evaluation_id": "eval-cli"})
    _configure(monkeypatch, database, key)

    assert main(["check"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "ok",
        "stored_audits": 1,
        "stored_profiles": 1,
    }
    assert main(["backup", "--output", str(backup)]) == 0
    assert json.loads(capsys.readouterr().out)["backup_path"] == str(backup.resolve())
    assert EncryptedProfileStore(backup, key).verify_integrity() == (1, 1)


def test_maintenance_cli_rotates_encryption_and_reports_existing_backup(tmp_path, monkeypatch, capsys):
    database = tmp_path / "profiles.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    old_key = EncryptedProfileStore.generate_key()
    new_key = EncryptedProfileStore.generate_key()
    store = EncryptedProfileStore(database, old_key)
    store.put("learner_rotate", {"user_id": "learner_rotate"})
    store.append_audit({"evaluation_id": "eval-rotate"})
    backup.touch()
    _configure(monkeypatch, database, new_key, decryption_keys=old_key)

    assert main(["backup", "--output", str(backup)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert main(["rotate-encryption"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "rotated_audits": 1,
        "rotated_profiles": 1,
        "status": "ok",
    }
    assert EncryptedProfileStore(database, new_key).verify_integrity() == (1, 1)


def test_maintenance_cli_refuses_to_create_missing_store(tmp_path, monkeypatch, capsys):
    database = tmp_path / "missing.sqlite3"
    _configure(monkeypatch, database, EncryptedProfileStore.generate_key())
    assert main(["check"]) == 1
    assert "does not exist" in capsys.readouterr().err
    assert not database.exists()
