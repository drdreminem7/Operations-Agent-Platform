from .recent_deployments import GetRecentDeploymentsTool
from .registry import ToolRegistry
from .restart_service import RestartServiceTool
from .rollback_deployment import RollbackDeploymentTool
from .search_logs import SearchLogsTool
from .service_health import GetServiceHealthTool
from .simulator import Simulator


def create_default_registry(simulator: Simulator | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    simulator = simulator or Simulator()
    registry.register(GetServiceHealthTool(simulator))
    registry.register(SearchLogsTool(simulator))
    registry.register(GetRecentDeploymentsTool(simulator))
    registry.register(RestartServiceTool(simulator))
    registry.register(RollbackDeploymentTool(simulator))
    return registry
