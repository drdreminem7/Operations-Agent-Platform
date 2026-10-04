from sqlalchemy.orm import Session

from app.agent.repository import AgentRunRepository
from app.agent.run import RunTransition
from app.agent.states import RunState
from app.database import engine
from app.models import Incident


def test_repository_creates_and_reloads_run() -> None:
    with Session(engine) as session:
        incident = Incident(
            title="Repository test incident",
            service="checkout",
            severity="high",
            status="open",
        )
        session.add(incident)
        session.commit()
        session.refresh(incident)
        incident_id = incident.id

    repository = AgentRunRepository(engine)
    run_id = repository.create_run(incident_id)

    loaded_run = repository.get_run(run_id)

    assert loaded_run is not None
    assert loaded_run.id == run_id
    assert loaded_run.incident_id == incident_id
    assert loaded_run.status == "running"
    assert loaded_run.current_state == "new"


def test_repository_persists_run_transition() -> None:
    with Session(engine) as session:
        incident = Incident(
            title="Repository test incident",
            service="checkout",
            severity="high",
            status="open",
        )
        session.add(incident)
        session.commit()
        session.refresh(incident)
        incident_id = incident.id

    repository = AgentRunRepository(engine)
    run_id = repository.create_run(incident_id)

    transition = RunTransition(
        sequence_number=1,
        state_before=RunState.NEW,
        state_after=RunState.TRIAGE,
    )

    repository.record_transition(
        run_id,
        transition,
        step_type="state_transition",
        reason="Begin incident triage",
    )

    loaded_run = repository.get_run(run_id)
    steps = repository.list_steps(run_id)

    assert loaded_run is not None
    assert loaded_run.current_state == "triage"
    assert loaded_run.status == "running"
    assert len(steps) == 1
    assert steps[0].sequence_number == 1
    assert steps[0].state_before == "new"
    assert steps[0].state_after == "triage"
    assert steps[0].reason == "Begin incident triage"
