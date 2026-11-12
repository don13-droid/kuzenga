from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import staging_preflight


def test_malformed_environment_file_does_not_log_its_contents(tmp_path, caplog):
    secret = "synthetic-test-secret-never-real"
    selected = tmp_path / ".env.staging"
    selected.write_text("malformed " + secret, encoding="utf-8")
    with pytest.raises(ValueError, match="single-line"):
        staging_preflight.load_environment(selected)
    assert secret not in caplog.text


def test_loader_refuses_repository_source_as_environment_input():
    with pytest.raises(ValueError, match="Git-ignored"):
        staging_preflight.load_environment(Path(staging_preflight.__file__))


@pytest.mark.parametrize("url", [
    "postgresql://fake:fake@other.invalid/staging?sslmode=require",
    "postgresql://fake:fake@staging.invalid/production?sslmode=require",
    "postgresql://fake:fake@staging.invalid/staging?sslmode=disable",
])
def test_database_probe_rejects_wrong_target_or_insecure_url_without_connecting(monkeypatch, url):
    connect = Mock()
    monkeypatch.setattr(staging_preflight.psycopg, "connect", connect)
    with pytest.raises(ValueError, match="selected staging target"):
        staging_preflight.verify_database(url, "staging.invalid", "staging")
    connect.assert_not_called()


def test_preflight_refuses_production_before_contacting_services(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setattr("sys.argv", ["staging_preflight.py", "--database"])
    verify = Mock()
    monkeypatch.setattr(staging_preflight, "verify_database", verify)
    with pytest.raises(SystemExit) as result:
        staging_preflight.main()
    assert result.value.code == 2
    verify.assert_not_called()
