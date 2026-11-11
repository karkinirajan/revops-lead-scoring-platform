from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    auth,
    companies,
    contacts,
    ingest,
    integrations,
    intelligence,
    model_registry,
    scoring,
    system,
    webhooks,
)

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
router.include_router(companies.router, prefix="/companies", tags=["companies"])
router.include_router(scoring.router, prefix="/scoring", tags=["scoring"])
router.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
router.include_router(model_registry.router, prefix="/models", tags=["models"])
router.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
router.include_router(system.router, prefix="/system", tags=["system"])
# Intelligence routes are mounted at root /api/v1 to keep paths clean
router.include_router(intelligence.router, tags=["intelligence"])
