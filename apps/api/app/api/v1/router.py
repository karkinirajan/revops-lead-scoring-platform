from fastapi import APIRouter

from app.api.v1 import auth, companies, contacts, ingest, scoring

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
router.include_router(companies.router, prefix="/companies", tags=["companies"])
router.include_router(scoring.router, prefix="/scoring", tags=["scoring"])
router.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
