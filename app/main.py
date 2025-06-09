# main.py - Enhanced version with organized service-based tags
import sys
import os
import time
import logging
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

# Your existing path setup
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

# UPDATED: Organized tags metadata by service categories
tags_metadata = [
    # Authentication & Core
    {
        "name": "Authentication",
        "description": "User registration, login, logout, and JWT token management.",
    },
    {
        "name": "OAuth Integrations", 
        "description": "Connect third-party services securely using OAuth2 flows.",
    },
    
    # Core Chat & AI
    {
        "name": "Chat & AI",
        "description": "AI-powered conversational interface with context-aware suggestions.",
    },
    
    # Google Services
    {
        "name": "Google Calendar",
        "description": "Google Calendar integration - list, create, update, delete events.",
    },
    {
        "name": "Gmail",
        "description": "Gmail integration - list messages, compose, send emails.",
    },
    {
        "name": "Google Drive", 
        "description": "Google Drive integration - file uploads and sharing.",
    },
    
    # Communication Services
    {
        "name": "Slack",
        "description": "Slack workspace integration - channels, messaging, team communication.",
    },
    {
        "name": "Zoom",
        "description": "Zoom meeting integration - create meetings, manage schedules.",
    },
    
    # Productivity Services
    {
        "name": "Notion",
        "description": "Notion workspace integration - pages, documents, task management.",
    },
    
    # Task & Automation
    {
        "name": "Task Execution",
        "description": "Execute automated workflows across integrated services.",
    },
    {
        "name": "Recommendations",
        "description": "AI-powered task suggestions and productivity recommendations.",
    },
    
    # System & Utilities
    {
        "name": "Utilities",
        "description": "System health, metrics, file downloads, and general utilities.",
    },
]

# Your existing FastAPI middleware imports
from fastapi.middleware.cors import CORSMiddleware
from app.routes import router as app_routes
from auth.auth_routes import router as auth_routes

# Your existing database setup (keep as-is)
from utils.db import Base, engine, SessionLocal
from sqlalchemy import create_engine
from models import user, user_token

# Your existing database configuration
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL is None:
    raise ValueError("DATABASE_URL environment variable not set")

print("Loaded DATABASE_URL:", DATABASE_URL)

# Keep your existing engine creation
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(bind=engine)

# Your existing DB dependency (keep as-is)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Enhanced FastAPI app with organized tags
app = FastAPI(
    title="Smart Productivity Assistant API",
    description="""
    🚀 **Smart Productivity Assistant** - Your AI-powered productivity companion
    
    ## Features
    
    ### 🤖 AI-Powered Chat
    - Context-aware conversations
    - Intelligent task suggestions
    - Multi-service integration
    
    ### 📅 Google Services
    - **Calendar**: Event management and scheduling
    - **Gmail**: Email composition and management  
    - **Drive**: File storage and sharing
    
    ### 💬 Communication
    - **Slack**: Team messaging and channels
    - **Zoom**: Video meetings and scheduling
    
    ### 📝 Productivity
    - **Notion**: Document and task management
    - **Task Automation**: Cross-platform workflows
    
    ### 🔐 Security
    - OAuth2 integration for all services
    - JWT authentication
    - Secure token management
    """,
    version="1.0.0",
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Your existing CORS setup (keep as-is)
origins = [
    "http://localhost:5173",
    "http://localhost:5174", 
    "https://chat.data-ai.co"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Your existing permissive setting
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# NEW: Add compatible middleware (safe to add)
try:
    from middleware.compatible_middleware import (
        SecurityHeadersMiddleware,
        RequestLoggingMiddleware,
        # BasicRateLimitMiddleware
    )
    
    # Add new middleware (safe additions)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    # app.add_middleware(BasicRateLimitMiddleware)
    
    print("✅ Enhanced middleware loaded successfully")
except ImportError:
    print("⚠️ Enhanced middleware not found - using basic setup")

# UPDATED: Route mounting with organized tags
try:
    app.include_router(
        app_routes, 
        tags=[
            "Chat & AI", 
            "Google Calendar", 
            "Gmail", 
            "Google Drive",
            "Slack", 
            "Zoom", 
            "Notion", 
            "Task Execution", 
            "Recommendations", 
            "Utilities"
        ]
    )
except Exception as e:
    print(f"Error including app_routes: {str(e)}")
    raise

app.include_router(
    auth_routes, 
    tags=["Authentication", "OAuth Integrations"]
)

# NEW: Add health check endpoints (safe additions)
app_start_time = time.time()

@app.get("/health", tags=["Utilities"])
async def health_check():
    """Enhanced health check endpoint"""
    try:
        # Test database connection using your existing setup
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        db_healthy = True
        db_error = None
    except Exception as e:
        db_healthy = False
        db_error = str(e)
    
    uptime = time.time() - app_start_time
    
    return {
        "healthy": db_healthy,
        "uptime_seconds": round(uptime, 2),
        "version": "1.0.0",
        "database": {
            "healthy": db_healthy,
            "error": db_error
        },
        "timestamp": time.time()
    }

@app.get("/metrics", tags=["Utilities"])
async def get_metrics():
    """Basic metrics endpoint"""
    uptime = time.time() - app_start_time
    
    return {
        "uptime_seconds": round(uptime, 2),
        "version": "1.0.0",
        "environment": "development" if os.getenv("DEBUG", "false").lower() == "true" else "production",
        "database_url_configured": bool(DATABASE_URL),
        "middleware_enabled": True
    }

# NEW: Enhanced error handling (safe addition)
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Better validation error responses"""
    errors = []
    for error in exc.errors():
        errors.append({
            "field": " -> ".join(str(x) for x in error["loc"][1:]),
            "message": error["msg"],
            "type": error["type"]
        })
    
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Validation failed",
            "errors": errors
        }
    )

@app.exception_handler(500)
async def internal_server_error_handler(request: Request, exc: Exception):
    """Global error handler"""
    logging.error(f"Unhandled error on {request.url.path}: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal server error",
            "support": "Contact support if this error persists"
        }
    )

# Your existing startup message
if __name__ == "__main__":
    print("🚀 Enhanced Smart Productivity Assistant API starting...")
    print("📚 API Documentation available at: http://localhost:8000/docs")
    print("📖 Alternative docs at: http://localhost:8000/redoc")
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )