from ..tools.result import ToolResult


def supports_rollback(
    evidence: list[ToolResult], *, service: str, version: str
) -> bool:
    degraded = any(
        result.tool_name == "get_service_health"
        and result.output.get("service") == service
        and result.output.get("status") == "degraded"
        for result in evidence
    )
    error_log = False
    active_deployment = False
    for result in evidence:
        if result.output.get("service") != service:
            continue
        if result.tool_name == "search_logs":
            matches = result.output.get("matches")
            if isinstance(matches, list):
                error_log = error_log or any(
                    isinstance(match, dict)
                    and match.get("service") == service
                    and match.get("level") == "error"
                    for match in matches
                )
        if result.tool_name == "get_recent_deployments":
            deployments = result.output.get("deployments")
            if isinstance(deployments, list):
                active_deployment = active_deployment or any(
                    isinstance(deployment, dict)
                    and deployment.get("service") == service
                    and deployment.get("version") == version
                    and deployment.get("environment") == "production"
                    and deployment.get("status") == "successful"
                    for deployment in deployments
                )
    return degraded and error_log and active_deployment
