import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import settings  # noqa: E402


def test_example_profile_is_complete(monkeypatch):
    monkeypatch.setattr(settings, "PROFILE", settings.PROFILE_EXAMPLE)
    s = settings.settings()
    for k in settings.REQUIRED:
        assert s[k]
    assert s["jobs_root"].endswith("/resume/jobs")
    assert s["categories"]  # config.yaml merged in


def test_missing_profile_fails_loudly(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "PROFILE", tmp_path / "nope.yaml")
    with pytest.raises(SystemExit):
        settings.settings()
    assert settings.settings(require_profile=False)["max_jobs"]
