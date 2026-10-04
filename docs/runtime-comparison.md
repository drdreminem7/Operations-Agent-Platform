# Runtime comparison: custom engine and LangGraph

The isolated experiment in `src/app/experiments/langgraph_workflow.py` runs the
same synthetic checkout-deployment investigation as the application engine.
It gathers three read results, proposes a rollback only with corroborating
evidence, pauses for a decision, performs a simulator-only rollback after
approval, and verifies recovery. It is not mounted in the API and does not
replace the application runtime.

Run the experiment tests with the optional dependency group:

```bash
uv sync --group experiment
uv run pytest tests/test_langgraph_experiment.py
```

| Concern | Custom runtime | Isolated LangGraph experiment |
|---|---|---|
| Workflow state | Explicit `AgentRun` and legal transition table | `StateGraph` nodes and conditional edges |
| Pause/resume | Approval row and run state committed in PostgreSQL | `interrupt()` and `Command(resume=...)` with an in-memory checkpointer |
| Persistence | Numbered audit steps, transaction boundaries, approval/action/job rows | Graph checkpoints in process memory for this experiment |
| Write safety | Action hash, DB claim, single-use approval, uncertain state, no automatic replay | Local boolean resume and simulated execution; no durable action-intent claim |
| Background work | PostgreSQL job lease, heartbeat, token fencing | Not modeled in this experiment |
| Tool policy | Server-owned policy and typed executor | Reuses the same policy and executor, but no API operator authentication |

LangGraph removes some orchestration code: node scheduling, conditional edges,
checkpoint storage at node boundaries, and a built-in pause/resume primitive.
Its [StateGraph reference](https://reference.langchain.com/python/langgraph/graph/state/StateGraph)
describes nodes as functions that update shared state, while the
[interrupt reference](https://reference.langchain.com/python/langgraph/types/interrupt)
states that an interrupted node re-executes from its beginning on resume.
That is why this experiment does no side effect before `interrupt()`.
The [in-memory checkpointer](https://reference.langchain.com/python/langgraph.checkpoint/memory/InMemorySaver)
is explicitly for debugging and testing, not process-durable production use.

For this system, a graph checkpoint alone would not replace the existing
transactional approval record, action-specific hash, side-effect claim,
uncertain-write handling, or worker lease fencing. Those are application
invariants and must remain server-owned even if a future graph coordinates
steps. The experiment proves pause/approve/deny behavior locally; it does not
prove process restart recovery. A fairer production comparison would add a
PostgreSQL checkpointer and reproduce the same crash tests before considering
a migration. Until then, the custom engine remains the API runtime.
