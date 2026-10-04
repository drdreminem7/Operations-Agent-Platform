import asyncio
from dataclasses import replace
from pathlib import Path

from app.evaluation.gate import check_gate, load_baseline
from app.evaluation.runner import ScenarioResult, evaluate_scenario
from app.evaluation.scenario import load_scenarios

ROOT = Path(__file__).resolve().parents[1]


def baseline_results() -> list[ScenarioResult]:
    async def evaluate() -> list[ScenarioResult]:
        return [
            await evaluate_scenario(scenario)
            for scenario in load_scenarios(ROOT / "evals" / "scenarios")
        ]

    return asyncio.run(evaluate())


def test_gate_accepts_reviewed_baseline() -> None:
    summary, failures = check_gate(
        baseline_results(), load_baseline(ROOT / "evals" / "baseline.json")
    )

    assert summary.passed == 20
    assert failures == []


def test_gate_rejects_removed_scenario() -> None:
    results = baseline_results()[:-1]
    _, failures = check_gate(results, load_baseline(ROOT / "evals" / "baseline.json"))

    assert any(failure.startswith("missing scenarios:") for failure in failures)


def test_gate_rejects_unsafe_action_even_if_outcome_passes() -> None:
    results = baseline_results()
    results[0] = replace(results[0], unsafe_action_execution=True)
    _, failures = check_gate(results, load_baseline(ROOT / "evals" / "baseline.json"))

    assert "unsafe action executions above baseline" in failures


def test_gate_rejects_tool_call_regression() -> None:
    results = baseline_results()
    results[0] = replace(results[0], tool_calls=results[0].tool_calls * 6)
    _, failures = check_gate(results, load_baseline(ROOT / "evals" / "baseline.json"))

    assert "mean tool calls above baseline" in failures
