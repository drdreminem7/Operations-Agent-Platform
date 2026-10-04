import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from .gate import check_gate, load_baseline
from .metrics import summarize
from .runner import evaluate_scenario
from .scenario import load_scenarios


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate simulated agent incidents")
    parser.add_argument(
        "--scenarios", type=Path, default=Path("evals/scenarios")
    )
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    results = [
        await evaluate_scenario(scenario)
        for scenario in load_scenarios(args.scenarios)
    ]
    summary = summarize(results)
    failures: list[str] = []
    if args.baseline is not None:
        summary, failures = check_gate(results, load_baseline(args.baseline))
    print(
        json.dumps(
            {
                "summary": asdict(summary),
                "gate": {"passed": not failures, "failures": failures}
                if args.baseline is not None
                else None,
                "scenarios": [asdict(result) for result in results],
            },
            indent=2,
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
