# Local performance baseline

Run the read-only benchmark from the repository root:

```bash
LOG_LEVEL=ERROR PYTHONPATH=src uv run python -m app.benchmarks.control_plane --iterations 100 --with-database
```

Without `--with-database`, the script measures only `/health` and a complete
in-memory deterministic escalation. The database mode adds a pooled `SELECT 1`
and `/ready`. It creates no incidents or jobs. Each operation runs serially,
with up to ten warmups; p50/p95/p99 use nearest rank. The JSON output records
the platform, Python version, CPU count, sample size, wall/process CPU time,
and peak process RSS. HTTP requests use FastAPI's in-process `TestClient`, not
a network load generator.

On 2026-10-04, a 100-iteration run on macOS 14.8.5, arm64, Python 3.12.10,
10 logical CPUs, and local PostgreSQL produced:

| Operation | p50 | p95 | p99 | Serial operations/s |
|---|---:|---:|---:|---:|
| `GET /health` | 1.33 ms | 1.58 ms | 1.76 ms | 732 |
| In-memory agent escalation | 0.28 ms | 0.37 ms | 0.42 ms | 3,354 |
| Pooled database `SELECT 1` | 0.64 ms | 0.92 ms | 0.95 ms | 1,470 |
| `GET /ready` | 1.96 ms | 2.15 ms | 2.20 ms | 502 |

The entire benchmark process used 0.32 CPU seconds over 0.54 wall seconds and
reached 104 MB peak RSS. These are single-machine, concurrency-one measurements
after warmup, not service capacity or a production latency SLO. The agent
measurement excludes a model call, worker lease/DB persistence, and human
approval wait. The `/ready` measurement includes the local database query;
its roughly 0.6 ms higher median than `/health` is consistent with that extra
work, but this sample does not establish a bottleneck or justify an
optimization. No before/after optimization experiment has been claimed.

Before making performance changes, repeat the baseline under a stable machine
load, measure concurrent workers and real model calls separately, and profile
the slow path. Record the hypothesis, single change, before/after result, and
trade-off rather than treating this one local run as universal.
