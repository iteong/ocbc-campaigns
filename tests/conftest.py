"""Shared fixtures: synthetic data built in memory (same seeds as src/data_gen.py)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core  # noqa: E402
import data_gen  # noqa: E402


@pytest.fixture(scope="session")
def customers():
    """All synthetic customers plus the simulated past campaign."""
    return data_gen.simulate_campaign(data_gen.generate_customers())


@pytest.fixture(scope="session")
def scored_all(customers):
    """Every customer scored, deliberately NOT pre-filtered, so targeting must do the filtering."""
    return core.score_customers(core.fit_models(customers), customers)
