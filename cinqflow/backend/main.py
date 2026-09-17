from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from backend.core.config import settings
from backend.api import auth, contracts, feeds, inputs, pipeline, quarantine, reconciliation, audit, merge_split, profiling, schemas, onboarding, canonical_models, mappings, rules, schedules, dependencies, glossary, ops, ops_incidents, ops_governance, ods, identity

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown

app = FastAPI(
    title="CINQFLOW API",
    description="Healthcare data platform — Wave 0 & Wave 1",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(contracts.router, prefix="/api/v1/contracts", tags=["Contract Register"])
app.include_router(feeds.router, prefix="/api/v1/feeds", tags=["Feed Registry"])
app.include_router(inputs.router, prefix="/api/v1/inputs", tags=["Input Registry"])
app.include_router(pipeline.router, prefix="/api/v1/pipeline", tags=["Pipeline"])
app.include_router(quarantine.router, prefix="/api/v1/quarantine", tags=["Quarantine"])
app.include_router(reconciliation.router, prefix="/api/v1/reconciliation", tags=["Reconciliation"])
app.include_router(audit.router, prefix="/api/v1/audit", tags=["Audit"])
app.include_router(merge_split.router, prefix="/api/v1/identity/proposals", tags=["Identity Proposals"])
app.include_router(profiling.router, prefix="/api/v1", tags=["Profiling & Samples"])
app.include_router(schemas.router, prefix="/api/v1/schemas", tags=["Schema Contracts"])
app.include_router(onboarding.router, prefix="/api/v1/onboarding", tags=["Feed Onboarding"])
app.include_router(canonical_models.router, prefix="/api/v1/canonical-models", tags=["Canonical Models"])
app.include_router(mappings.router, prefix="/api/v1/mappings", tags=["Mapping Studio"])
app.include_router(rules.router, prefix="/api/v1/rules", tags=["Data Quality Rules"])
app.include_router(schedules.router, prefix="/api/v1/schedules", tags=["Feed Schedules"])
app.include_router(dependencies.router, prefix="/api/v1/dependencies", tags=["Feed Dependencies"])
app.include_router(glossary.router, prefix="/api/v1/glossary", tags=["Business Glossary"])
app.include_router(ops.router, prefix="/api/v1/ops", tags=["Operations Control Center"])
app.include_router(ops_incidents.router, prefix="/api/v1/ops", tags=["Operations Incidents & Alerts"])
app.include_router(ops_governance.router, prefix="/api/v1/ops", tags=["Operations Governance & Certifications"])
app.include_router(ods.router, prefix="/api/v1/ods", tags=["Canonical ODS"])
app.include_router(identity.router, prefix="/api/v1/identity", tags=["Identity Resolution"])

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV, "wave": "0"}

@app.get("/api/v1/health", tags=["Health"])
def api_health_check():
    from backend.core.database import engine
    try:
        with engine.connect() as conn:
            conn.execute(__import__('sqlalchemy').text('SELECT 1'))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    return {"status": "ok", "database": db_status, "wave": "0"}