import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.scenario import Scenario, load_scenarios

SCENARIOS = Path(__file__).resolve().parents[1] / "evals" / "scenarios"


def test_scenario_dataset_has_distinct_expected_outcomes() -> None:
    scenarios = load_scenarios(SCENARIOS)

    assert len(scenarios) == 20
    assert len({scenario.id for scenario in scenarios}) == len(scenarios)
    assert {str(scenario.expected.final_state) for scenario in scenarios} == {
        "resolved",
        "escalated",
        "awaiting_approval",
    }


def test_scenario_rejects_overlapping_required_and_forbidden_tools() -> None:
    scenario = load_scenarios(SCENARIOS)[0].model_dump()
    scenario["expected"]["forbidden_tools"].append("search_logs")

    with pytest.raises(ValidationError, match="cannot overlap"):
        Scenario.model_validate(scenario)


def test_scenario_rejects_extra_fields() -> None:
    scenario = load_scenarios(SCENARIOS)[0].model_dump()
    scenario["environment"]["unknown"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Scenario.model_validate(scenario)


def test_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    scenario = load_scenarios(SCENARIOS)[0].model_dump(mode="json")
    (tmp_path / "first.json").write_text(json.dumps(scenario))
    (tmp_path / "second.json").write_text(json.dumps(scenario))

    with pytest.raises(ValueError, match="Duplicate scenario ID"):
        load_scenarios(tmp_path)


def test_loader_rejects_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No scenarios found"):
        load_scenarios(tmp_path)
