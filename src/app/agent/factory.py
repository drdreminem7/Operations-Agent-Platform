from ..tools.defaults import create_default_registry
from ..tools.executor import ToolExecutor
from ..tools.simulator import Simulator
from .engine import AgentEngine
from .providers.factory import create_decision_provider
from .repository import AgentRunRepository


def create_agent_engine(repository: AgentRunRepository) -> AgentEngine:
    return AgentEngine(
        create_decision_provider(),
        repository=repository,
        tool_executor_factory=lambda run: ToolExecutor(
            create_default_registry(Simulator.from_results(run.tool_results))
        ),
    )
