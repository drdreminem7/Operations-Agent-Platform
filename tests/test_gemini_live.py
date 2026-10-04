import asyncio
import os

import pytest

from app.agent.providers.gemini import (
    GeminiDecisionProvider,
    GoogleGenAIStructuredOutputGenerator,
)


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_GEMINI_LIVE") != "1",
    reason="RUN_GEMINI_LIVE is not enabled",
)
def test_gemini_returns_valid_tool_request() -> None:
    generator = GoogleGenAIStructuredOutputGenerator(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30")),
    )
    provider = GeminiDecisionProvider(generator)

    request = asyncio.run(
        provider.choose_tool(
            title="Checkout latency increased",
            service="checkout",
            description="Latency rose after the latest release.",
        )
    )

    assert request.tool_name in {
        "get_service_health",
        "search_logs",
        "get_recent_deployments",
    }
    assert request.arguments["service"] == "checkout"
