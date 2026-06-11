"""Tests for minimal hardening: DB URL override, stale-run reconciliation,
plaintext-secret warnings."""

import logging
from datetime import datetime, timedelta, timezone

from testmcpy.mcp_profiles import _warn_plaintext_secrets
from testmcpy.storage import TestStorage


class TestDbUrlOverride:
    def test_db_url_env_used_when_no_path(self, tmp_path, monkeypatch):
        url = f"sqlite:///{tmp_path / 'via_url.db'}"
        monkeypatch.setenv("TESTMCPY_DB_URL", url)
        storage = TestStorage()
        assert storage.db_path is None
        assert str(storage._engine.url) == url

    def test_explicit_path_beats_db_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TESTMCPY_DB_URL", "sqlite:///should-not-be-used.db")
        storage = TestStorage(db_path=tmp_path / "explicit.db")
        assert storage.db_path == tmp_path / "explicit.db"

    def test_get_db_url_helper(self, tmp_path, monkeypatch):
        from testmcpy.db import get_db_url

        monkeypatch.setenv("TESTMCPY_DB_URL", "postgresql+psycopg://u:p@h/db")
        assert get_db_url() == "postgresql+psycopg://u:p@h/db"
        assert get_db_url(tmp_path / "x.db").startswith("sqlite:///")


class TestStaleRunReconciliation:
    def test_old_running_rows_marked_interrupted(self, tmp_path):
        storage = TestStorage(db_path=tmp_path / "t.db")
        old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        fresh = datetime.now(timezone.utc).isoformat()
        storage.save_run(
            run_id="stale", test_id="s", test_version=1, model="m", provider="p", started_at=old
        )
        storage.save_run(
            run_id="fresh", test_id="s", test_version=1, model="m", provider="p", started_at=fresh
        )
        storage.save_run(
            run_id="done", test_id="s", test_version=1, model="m", provider="p", started_at=old
        )
        storage.complete_run("done", old)

        updated = storage.mark_stale_runs_interrupted(no_heartbeat_older_than_hours=1.0)
        assert updated == 1

        with storage.session() as session:
            from testmcpy.models import TestRunModel

            statuses = {r.run_id: r.status for r in session.query(TestRunModel).all()}
        assert statuses["stale"] == "interrupted"
        assert statuses["fresh"] == "running"
        assert statuses["done"] == "completed"


class TestPlaintextSecretWarning:
    def test_literal_secret_warns(self, caplog):
        config = {
            "profiles": {
                "prod": {
                    "mcps": [{"auth": {"type": "jwt", "api_secret": "sk-live-abcdef123456789"}}]
                }
            }
        }
        with caplog.at_level(logging.WARNING, logger="testmcpy.mcp_profiles"):
            _warn_plaintext_secrets(config, "x.yaml")
        assert "plaintext secrets" in caplog.text
        assert "api_secret" in caplog.text

    def test_env_var_reference_is_fine(self, caplog):
        config = {"auth": {"api_secret": "${MCP_API_SECRET}", "api_token": "${MCP_TOKEN}"}}
        with caplog.at_level(logging.WARNING, logger="testmcpy.mcp_profiles"):
            _warn_plaintext_secrets(config, "x.yaml")
        assert "plaintext secrets" not in caplog.text

    def test_short_placeholder_ignored(self, caplog):
        config = {"auth": {"token": "none"}}
        with caplog.at_level(logging.WARNING, logger="testmcpy.mcp_profiles"):
            _warn_plaintext_secrets(config, "x.yaml")
        assert "plaintext secrets" not in caplog.text

    def test_non_secret_keys_ignored(self, caplog):
        config = {"mcp_url": "https://example.com/very/long/mcp/endpoint/url"}
        with caplog.at_level(logging.WARNING, logger="testmcpy.mcp_profiles"):
            _warn_plaintext_secrets(config, "x.yaml")
        assert "plaintext secrets" not in caplog.text
