"""Fail-fast validation of MinIO endpoint env vars (fix-minio-domain-artifacts).

``src.settings`` binds ``MINIO_ENDPOINT``/``MINIO_SECURE`` (and the
``MINIO_PUBLIC_*`` overrides) at import time from ``minio_host`` /
``MINIO_PUBLIC_HOST``. A scheme-less value (``file.example.com`` instead of
``https://file.example.com``) makes ``urlparse`` return an empty netloc, which
used to surface only as a per-request ``RuntimeError`` in the artifact
download path.

The raise contract is pinned by calling ``_validated_minio_url`` directly:
``importlib.reload`` redefines ``ConfigError`` as a new class object, so a
``pytest.raises(settings.ConfigError)`` captured before the reload would not
match the exception the reloaded module raises. The binding contract (env ->
``MINIO_*`` constants, fallback semantics) is pinned with reload under a
monkeypatched environment, reloading again afterwards so later tests see the
real environment's settings.
"""

from __future__ import annotations

import importlib

import pytest

import src.settings as settings


def _reload() -> None:
    """Re-bind src.settings module constants from the current environment."""
    importlib.reload(settings)


@pytest.fixture(autouse=True)
def _restore_settings():
    """Reload settings with the test session's original env after each case."""
    yield
    _reload()


def test_schemeless_minio_host_is_rejected():
    with pytest.raises(settings.ConfigError) as exc:
        settings._validated_minio_url("minio_host", "file.token118.com")
    msg = str(exc.value)
    assert "minio_host" in msg
    assert "file.token118.com" in msg


def test_schemeless_public_host_override_is_rejected():
    with pytest.raises(settings.ConfigError) as exc:
        settings._validated_minio_url("MINIO_PUBLIC_HOST", "china-minio:9000")
    msg = str(exc.value)
    assert "MINIO_PUBLIC_HOST" in msg
    assert "china-minio:9000" in msg


def test_empty_value_passes_through_unvalidated():
    # Empty means "unset": localhost default (minio_host) / origin fallback
    # (MINIO_PUBLIC_HOST) apply downstream, so the helper lets it through.
    assert settings._validated_minio_url("MINIO_PUBLIC_HOST", "") == ""


def test_full_url_endpoints_bind_host_port_and_secure_flag(monkeypatch):
    monkeypatch.setenv("minio_host", "https://file.token118.com")
    monkeypatch.setenv(
        "MINIO_PUBLIC_HOST", "http://china-minio.law-bench.svc.cluster.local:9000"
    )
    _reload()
    assert settings.MINIO_ENDPOINT == "file.token118.com"
    assert settings.MINIO_SECURE is True
    assert (
        settings.MINIO_PUBLIC_ENDPOINT
        == "china-minio.law-bench.svc.cluster.local:9000"
    )
    assert settings.MINIO_PUBLIC_SECURE is False


def test_unset_public_host_falls_back_to_origin_values(monkeypatch):
    monkeypatch.setenv("minio_host", "http://23.144.68.246:30900")
    monkeypatch.delenv("MINIO_PUBLIC_HOST", raising=False)
    _reload()
    assert settings.MINIO_ENDPOINT == "23.144.68.246:30900"
    assert settings.MINIO_SECURE is False
    assert settings.MINIO_PUBLIC_ENDPOINT == settings.MINIO_ENDPOINT
    assert settings.MINIO_PUBLIC_SECURE == settings.MINIO_SECURE


def test_unset_minio_host_defaults_to_localhost(monkeypatch):
    # Neutralize load_dotenv for the reload: it locates .env from the settings
    # module's path (not CWD) and would re-populate minio_host after delenv.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("minio_host", raising=False)
    monkeypatch.delenv("MINIO_PUBLIC_HOST", raising=False)
    _reload()
    assert settings.MINIO_ENDPOINT == "localhost:9000"
    assert settings.MINIO_SECURE is False
