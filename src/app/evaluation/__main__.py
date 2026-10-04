import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from .metrics import summarize
from .runner import evaluate_scenario
from .scenario import load_scenarios


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate simulated agent incidents")
    parser.add_argument(
        "--scenarios", type=Path, default=Path("evals/scenarios")
    )
    args = parser.parse_args()
    results = [
        await evaluate_scenario(scenario)
        for scenario in load_scenarios(args.scenarios)
    ]
    print(
        json.dumps(
            {
                "summary": asdict(summarize(results)),
                "scenarios": [asdict(result) for result in results],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
