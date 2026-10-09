"""Shared test fixtures for the git-repokit-common suite.

Every git process the tests start -- directly, through a hook, or through a
script under test such as update-common.sh -- must never sign: on a machine
with commit.gpgsign = true a signed commit opens a GPG dialog mid-test and
asks a person to sign something they did not initiate (2026-10-09: the
update-common.sh tests' `git subtree pull` did exactly that). The tests that
call git themselves pass -c flags; this environment reaches the git calls made
by the code under test, which the tests cannot decorate.
"""

import os

import pytest
from pathlib import Path

_UNSIGNED_GIT_ENV = {
    "GIT_CONFIG_COUNT": "4",
    "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "tag.gpgsign", "GIT_CONFIG_VALUE_1": "false",
    "GIT_CONFIG_KEY_2": "user.email", "GIT_CONFIG_VALUE_2": "t@example.invalid",
    "GIT_CONFIG_KEY_3": "user.name", "GIT_CONFIG_VALUE_3": "t",
}


def pytest_configure(config):
    for key, value in _UNSIGNED_GIT_ENV.items():
        os.environ.setdefault(key, value)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory for testing."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def sample_data(tmp_path):
    """Create sample data files for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir
