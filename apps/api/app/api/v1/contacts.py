from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import AnalystRequired, CurrentUser, ViewerRequired
from app.database import get_db
from app.models.contact import Contact, ContactFeature
from app.schemas.common import PaginatedResponse
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate

router = APIRouter()


@router.get("", response_model=PaginatedResponse[ContactRead], dependencies=[ViewerRequired])
def list_contacts(
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    source_system: str | None = Query(None),
    lifecycle_stage: str | None = Query(None),
    search: str | None = Query(None, description="Search by email or name"),
):
    q = select(Contact)
    if source_system:
        q = q.where(Contact.source_system == source_system)
    if lifecycle_stage:
        q = q.where(Contact.lifecycle_stage == lifecycle_stage)
    if search:
        term = f"%{search.lower()}%"
        q = q.where(
            func.lower(Contact.email).like(term)
            | func.lower(Contact.first_name).like(term)
            | func.lower(Contact.last_name).like(term)
        )

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()

    return PaginatedResponse(
        items=list(items),
        total=total or 0,
        page=page,
        page_size=page_size,
        pages=max(1, -(-( total or 0) // page_size)),
    )


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED, dependencies=[AnalystRequired])
def create_contact(body: ContactCreate, db: Annotated[Session, Depends(get_db)]):
    existing = db.scalar(
        select(Contact).where(
            Contact.source_system == body.source_system,
            Contact.source_record_id == body.source_record_id,
        )
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Contact already exists for this source")

    contact = Contact(**body.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/{contact_id}", response_model=ContactRead, dependencies=[ViewerRequired])
def get_contact(contact_id: str, db: Annotated[Session, Depends(get_db)]):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


@router.patch("/{contact_id}", response_model=ContactRead, dependencies=[AnalystRequired])
def update_contact(contact_id: str, body: ContactUpdate, db: Annotated[Session, Depends(get_db)]):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AnalystRequired])
def delete_contact(contact_id: str, db: Annotated[Session, Depends(get_db)]):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    db.delete(contact)
    db.commit()
