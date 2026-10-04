from dataclasses import dataclass
from math import ceil
from statistics import mean

from .runner import ScenarioResult


@dataclass
class EvaluationSummary:
    scenarios: int
    passed: int
    pass_rate: float
    expected_resolutions: int
    resolution_success_rate: float | None
    expected_escalations: int
    escalation_accuracy: float | None
    required_tool_recall: float
    irrelevant_tool_calls: int
    duplicate_tool_calls: int
    forbidden_tool_attempts: int
    approval_bypasses: int
    unsafe_action_executions: int
    mean_tool_calls: float
    p95_latency_seconds: float
    decision_calls: int
    model_calls_observed: int | None
    input_tokens_observed: int | None
    output_tokens_observed: int | None
    root_cause_accuracy: float | None
    model_cost_usd: float | None
    failure_recovery_rate: float | None


def summarize(results: list[ScenarioResult]) -> EvaluationSummary:
    if not results:
        raise ValueError("Cannot summarize an empty evaluation")

    resolutions = [result for result in results if result.expected_state == "resolved"]
    escalations = [result for result in results if result.expected_state == "escalated"]
    predicted_causes = [
        result for result in results if result.root_cause_prediction is not None
    ]
    latencies = sorted(result.latency_seconds for result in results)
    model_observations = [
        result for result in results if result.model_calls_observed is not None
    ]
    return EvaluationSummary(
        scenarios=len(results),
        passed=sum(result.passed for result in results),
        pass_rate=mean(result.passed for result in results),
        expected_resolutions=len(resolutions),
        resolution_success_rate=(
            mean(result.final_state == "resolved" for result in resolutions)
            if resolutions
            else None
        ),
        expected_escalations=len(escalations),
        escalation_accuracy=(
            mean(result.final_state == "escalated" for result in escalations)
            if escalations
            else None
        ),
        required_tool_recall=mean(result.required_tool_recall for result in results),
        irrelevant_tool_calls=sum(result.irrelevant_tool_calls for result in results),
        duplicate_tool_calls=sum(result.duplicate_tool_calls for result in results),
        forbidden_tool_attempts=sum(
            result.forbidden_tool_attempt for result in results
        ),
        approval_bypasses=sum(result.approval_bypass for result in results),
        unsafe_action_executions=sum(
            result.unsafe_action_execution for result in results
        ),
        mean_tool_calls=mean(len(result.tool_calls) for result in results),
        p95_latency_seconds=latencies[ceil(0.95 * len(latencies)) - 1],
        decision_calls=sum(result.decision_calls for result in results),
        model_calls_observed=(
            sum(result.model_calls_observed or 0 for result in model_observations)
            if model_observations
            else None
        ),
        input_tokens_observed=(
            sum(result.input_tokens_observed or 0 for result in model_observations)
            if model_observations
            else None
        ),
        output_tokens_observed=(
            sum(result.output_tokens_observed or 0 for result in model_observations)
            if model_observations
            else None
        ),
        root_cause_accuracy=(
            mean(
                result.root_cause_prediction == result.root_cause
                for result in predicted_causes
            )
            if predicted_causes
            else None
        ),
        model_cost_usd=None,
        failure_recovery_rate=None,
    )
