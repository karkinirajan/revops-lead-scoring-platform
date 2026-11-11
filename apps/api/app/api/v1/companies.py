from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import AnalystRequired, ViewerRequired
from app.database import get_db
from app.models.company import Company
from app.schemas.common import PaginatedResponse
from app.schemas.company import CompanyCreate, CompanyRead, CompanyUpdate
from app.services.search_utils import LIKE_ESCAPE, contains_pattern

router = APIRouter()


@router.get("", response_model=PaginatedResponse[CompanyRead], dependencies=[ViewerRequired])
def list_companies(
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    size_tier: str | None = Query(None),
    industry: str | None = Query(None),
    search: str | None = Query(None),
):
    q = select(Company)
    if size_tier:
        q = q.where(Company.size_tier == size_tier)
    if industry:
        q = q.where(Company.industry == industry)
    if search:
        term = contains_pattern(search.lower())
        q = q.where(
            func.lower(Company.name).like(term, escape=LIKE_ESCAPE)
            | func.lower(Company.domain).like(term, escape=LIKE_ESCAPE)
        )

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()

    return PaginatedResponse(
        items=list(items),
        total=total or 0,
        page=page,
        page_size=page_size,
        pages=max(1, -(-(total or 0) // page_size)),
    )


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED, dependencies=[AnalystRequired])
def create_company(body: CompanyCreate, db: Annotated[Session, Depends(get_db)]):
    existing = db.scalar(
        select(Company).where(
            Company.source_system == body.source_system,
            Company.source_record_id == body.source_record_id,
        )
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Company already exists for this source")

    company = Company(**body.model_dump())
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/{company_id}", response_model=CompanyRead, dependencies=[ViewerRequired])
def get_company(company_id: str, db: Annotated[Session, Depends(get_db)]):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


@router.patch("/{company_id}", response_model=CompanyRead, dependencies=[AnalystRequired])
def update_company(company_id: str, body: CompanyUpdate, db: Annotated[Session, Depends(get_db)]):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(company, f, v)
    db.commit()
    db.refresh(company)
    return company
