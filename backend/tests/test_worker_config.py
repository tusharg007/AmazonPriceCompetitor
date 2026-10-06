"""Collection limits, lease timing and V1 error vocabulary compatibility."""

import pytest
from app.core.config import Settings
from app.models.enums import ScrapeErrorCode

from src.models import ScrapeErrorCode as V1Code


@pytest.mark.parametrize(
    "values",
    [
        {"worker_poll_interval": 0},
        {"worker_lease_seconds": 2},
        {"worker_heartbeat_seconds": 0},
        {"worker_lease_seconds": 15, "worker_heartbeat_seconds": 15},
        {"max_search_pages": 0},
        {"max_search_pages": 11},
        {"max_competitors": 0},
        {"max_competitors": 101},
        {"block_cooldown_seconds": -1},
    ],
)
def test_invalid_worker_configuration(values, tmp_path):
    with pytest.raises(ValueError):
        Settings(evidence_dir=tmp_path, **values)


def test_worker_configuration_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_WORKER_LEASE_SECONDS", "60")
    monkeypatch.setenv("APP_WORKER_HEARTBEAT_SECONDS", "5")
    monkeypatch.setenv("APP_WORKER_POLL_INTERVAL", "0.5")
    settings = Settings(evidence_dir=tmp_path)
    assert settings.worker_lease_seconds == 60
    assert settings.worker_heartbeat_seconds == 5 and settings.worker_poll_interval == 0.5


def test_v1_error_vocabulary_preserved():
    assert {code.value for code in ScrapeErrorCode} == {code.value for code in V1Code}
