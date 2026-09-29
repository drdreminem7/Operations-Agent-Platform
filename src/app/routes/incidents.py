from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import engine
from ..models import Incident
from ..schemas import IncidentCreate, IncidentResponse, IncidentUpdate

router = APIRouter()


@router.post("/incidents", response_model=IncidentResponse, status_code=201)
def create_incident(incident_data: IncidentCreate) -> Incident:
    with Session(engine) as session:
        incident = Incident(**incident_data.model_dump())
        session.add(incident)
        session.commit()
        session.refresh(incident)
        return incident


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: int) -> Incident:
    with Session(engine) as session:
        incident = session.get(Incident, incident_id)

        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")

        return incident


@router.get("/incidents", response_model=list[IncidentResponse])
def list_incidents(
    offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)
) -> list[Incident]:
    statement = (
        select(Incident)
        .order_by(Incident.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    with Session(engine) as session:
        incidents = session.scalars(statement).all()
        return list(incidents)


@router.patch("/incidents/{incident_id}", response_model=IncidentResponse)
def update_incident(incident_id: int, incident_data: IncidentUpdate) -> Incident:
    with Session(engine) as session:
        incident = session.get(Incident, incident_id)

        if incident is None:
            raise HTTPException(
                status_code=404,
                detail="Incident not found",
            )

        changes = incident_data.model_dump(exclude_unset=True)

        for field, value in changes.items():
            setattr(incident, field, value)

        session.commit()
        session.refresh(incident)
        return incident
