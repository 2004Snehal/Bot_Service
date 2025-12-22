#!/usr/bin/env python3
"""
Start the CueMeet Bot API server.

Usage:
    python run_server.py
    
Or with uvicorn directly:
    uvicorn server.app.main:app --reload --host 0.0.0.0 --port 8000
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Validate required env vars for API server
required_vars = ["DEEPGRAM_API_KEY", "GROQ_API_KEY"]
missing = [var for var in required_vars if not os.getenv(var)]
if missing:
    print(f"⚠️  Warning: Missing environment variables: {', '.join(missing)}")
    print("   The bots may not work correctly without these.")

# Start the server
if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    CueMeet Bot API                           ║
╠══════════════════════════════════════════════════════════════╣
║  Server: http://{host}:{port}                                   ║
║  Docs:   http://{host}:{port}/docs                              ║
║  Health: http://{host}:{port}/health                            ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    uvicorn.run(
        "server.app.main:app",
        host=host,
        port=port,
        reload=True
    )
