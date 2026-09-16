# CINQFLOW — Wave 0: Working Foundation

Healthcare data management platform.

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.12+ (for local backend dev)
- Node.js 20+ (for local frontend dev)

### Start with Docker
```bash
cd d:\Digitalurth\cinqflow
docker-compose up -d
```

### Local Development (without Docker)

**1. Start dependencies:**
```bash
docker-compose up -d postgres redis
```

**2. Backend:**
```bash
cd d:\Digitalurth\cinqflow
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

**3. Run migrations:**
```bash
alembic -c database/alembic.ini upgrade head
```

**4. Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Test Credentials (DEV only)
- Engineer: `engineer:engineer123`
- Read-Only: `readonly:readonly123`

## API Health
- http://localhost:8000/health
- http://localhost:8000/api/v1/health
- http://localhost:8000/docs

## Run Tests
```bash
pytest tests/ -v --cov=backend
```

## Wave 0 Scope
Pipeline: Landing → Bronze → Silver Raw → Quarantine → Reconciliation → Audit
No ODS, No Identity Resolution, No AI.
