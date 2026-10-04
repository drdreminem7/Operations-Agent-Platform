import hashlib
import json


def action_hash(run_id: int, tool_name: str, arguments: dict[str, object]) -> str:
    data = json.dumps(
        {"run_id": run_id, "tool_name": tool_name, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
