from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from ..agent.factory import create_agent_engine
from ..agent.providers.errors import ModelProviderError, ModelProviderTimeoutError
from ..agent.repository import AgentRunRepository
from ..database import engine
from ..jobs.queue import RunJobQueue
from ..models import (
    ActionExecutionRecord,
    AgentRunRecord,
    Incident,
    RunJobRecord,
    RunStepRecord,
)
from ..schemas import (
    ActionExecutionResponse,
    AgentRunResponse,
    RunJobResponse,
    RunStepResponse,
)
from ..tools.errors import ToolExecutionError

router = APIRouter()

repository = AgentRunRepository(engine)
queue = RunJobQueue(engine)
agent_engine = create_agent_engine(repository)


def _create_run(incident_id: int, *, enqueue: bool) -> AgentRunRecord:
    with Session(engine) as session:
        incident = session.get(Incident, incident_id)

    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    run_id = repository.create_run(incident_id, enqueue=enqueue)
    run_record = repository.get_run(run_id)

    if run_record is None:
        raise HTTPException(status_code=500, detail="Could not create run")

    return run_record


@router.post(
    "/incidents/{incident_id}/runs",
    response_model=AgentRunResponse,
    status_code=201,
)
def start_run(incident_id: int) -> AgentRunRecord:
    return _create_run(incident_id, enqueue=False)


@router.post(
    "/incidents/{incident_id}/runs/background",
    response_model=AgentRunResponse,
    status_code=201,
)
def start_background_run(incident_id: int) -> AgentRunRecord:
    return _create_run(incident_id, enqueue=True)


@router.get("/runs/{run_id}/job", response_model=RunJobResponse)
def get_run_job(run_id: int) -> RunJobRecord:
    if repository.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    job = queue.get_for_run(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/runs/{run_id}/job", response_model=RunJobResponse, status_code=202)
def enqueue_run(run_id: int) -> RunJobRecord:
    try:
        return queue.enqueue(run_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runs/{run_id}/step", response_model=AgentRunResponse)
async def step_run(run_id: int) -> AgentRunRecord:
    run = repository.load_run(run_id)

    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        await agent_engine.step(run)
    except ModelProviderTimeoutError as error:
        raise HTTPException(status_code=504, detail=str(error)) from error
    except ModelProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ToolExecutionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    run_record = repository.get_run(run_id)

    if run_record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return run_record


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
def get_run(run_id: int) -> AgentRunRecord:
    run_record = repository.get_run(run_id)

    if run_record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return run_record


@router.get("/runs/{run_id}/steps", response_model=list[RunStepResponse])
def get_run_steps(run_id: int) -> list[RunStepRecord]:
    run_record = repository.get_run(run_id)

    if run_record is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return repository.list_steps(run_id)


@router.get("/runs/{run_id}/execution", response_model=ActionExecutionResponse)
def get_run_execution(run_id: int) -> ActionExecutionRecord:
    if repository.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    execution = repository.get_execution(run_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution
