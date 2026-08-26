from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from server.app.api import bots, schedules, users
from server.app.db.database import engine, Base
from server.app.services.scheduler import start_scheduler
from server.app.services.session_manager import session_manager
from server.app.config.settings import settings
import logging
import os

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Hicapy Bot API",
    description="API service for managing Google Meet bots with API key authentication",
    version="1.0.0"
)

# Custom OpenAPI schema to properly declare security schemes
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Hicapy Bot API",
        version="1.0.0",
        description="""
API service for managing Google Meet bots with secure authentication.

## Authentication

This API uses two types of API key authentication:

### User API Key (X-API-Key)
- Required for all user endpoints (bots, meetings, schedules)
- Obtained after user registration
- Format: `cm_xxxxxxxxxxxxx`
- Pass in header: `X-API-Key: cm_your_key_here`

### Admin API Key (X-Admin-Key)
- Required for admin operations (user registration, admin endpoints)
- Set via ADMIN_API_KEY environment variable
- Pass in header: `X-Admin-Key: your_admin_key`

## Getting Started

1. **Register a user** (requires Admin Key):
   ```bash
   curl -X POST /api/users/register \\
     -H "X-Admin-Key: your_admin_key" \\
     -H "Content-Type: application/json" \\
     -d '{"user_id": "user123", "email": "user@example.com"}'
   ```

2. **Use the returned API key** for all other operations:
   ```bash
   curl -X GET /api/bots \\
     -H "X-API-Key: cm_returned_key"
   ```
        """,
        routes=app.routes,
    )
    
    # Define security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "User API key for accessing bot resources. Format: `cm_xxxxxxxxxxxxx`. Obtain this by registering a user with admin credentials."
        },
        "AdminKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Admin-Key",
            "description": "Admin API key for user registration and admin operations. Set via ADMIN_API_KEY environment variable."
        }
    }
    
    # Apply security to all paths (will be overridden per endpoint)
    # This ensures the Authorize button appears in Swagger UI
    openapi_schema["security"] = [
        {"ApiKeyAuth": []},
        {"AdminKeyAuth": []}
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers under /api prefix
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(bots.router, prefix="/api/bots", tags=["Bots"])
app.include_router(schedules.router, prefix="/api/schedules", tags=["Schedules"])

@app.on_event("startup")
def startup_event():
    logging.basicConfig(level=logging.INFO)
    start_scheduler()
    logging.info("Scheduler started")
    logging.info(f"TTS Microservice: {os.getenv('TTS_MICROSERVICE_URL', 'Not configured')}")
    
    # Security warning
    if not settings.ADMIN_API_KEY:
        logging.warning("⚠️  ADMIN_API_KEY not set! User registration will fail.")
        logging.warning("   Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    else:
        logging.info("✅ ADMIN_API_KEY configured")

@app.get("/")
def root():
    return {"message": "Bot API is running", "docs": "/docs"}

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "running_bots": len(session_manager.running_bots)
    }

@app.get("/api/running")
def list_running_bots():
    """List all currently running bots."""
    return session_manager.list_running_bots()
