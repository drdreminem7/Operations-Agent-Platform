import asyncio

import pytest

from app.tools.simulator import Simulator


def test_graph_pauses_before_write_and_resumes_after_approval() -> None:
    pytest.importorskip("langgraph")
    from langgraph.types import Command

    from app.experiments.langgraph_workflow import build_workflow

    simulator = Simulator()
    graph = build_workflow(simulator)
    config = {"configurable": {"thread_id": "approved-case"}}

    paused = asyncio.run(
        graph.ainvoke(
            {"title": "Checkout latency after deploy", "service": "checkout"},
            config,
        )
    )

    assert "__interrupt__" in paused
    assert simulator.deployments[0]["status"] == "successful"

    finished = asyncio.run(graph.ainvoke(Command(resume=True), config))

    assert finished["status"] == "resolved"
    assert simulator.deployments[0]["status"] == "rolled_back"


def test_graph_denial_escalates_without_write() -> None:
    pytest.importorskip("langgraph")
    from langgraph.types import Command

    from app.experiments.langgraph_workflow import build_workflow

    simulator = Simulator()
    graph = build_workflow(simulator)
    config = {"configurable": {"thread_id": "denied-case"}}

    asyncio.run(
        graph.ainvoke(
            {"title": "Checkout latency after deploy", "service": "checkout"},
            config,
        )
    )
    finished = asyncio.run(graph.ainvoke(Command(resume=False), config))

    assert finished["status"] == "escalated"
    assert simulator.deployments[0]["status"] == "successful"


def test_graph_escalates_without_corroborating_evidence() -> None:
    pytest.importorskip("langgraph")
    from app.experiments.langgraph_workflow import build_workflow

    simulator = Simulator()
    simulator.health["checkout"] = {"status": "healthy", "latency_ms": 100}
    graph = build_workflow(simulator)
    config = {"configurable": {"thread_id": "insufficient-evidence"}}

    finished = asyncio.run(
        graph.ainvoke(
            {"title": "Checkout latency after deploy", "service": "checkout"},
            config,
        )
    )

    assert finished["status"] == "escalated"
    assert simulator.deployments[0]["status"] == "successful"
