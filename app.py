"""Entry point for Databricks Apps (and local `python app.py`).

Databricks Apps injects the port to bind to; uvicorn serves the FastAPI app from app/api.py.
"""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", os.environ.get("PORT", "8000")))
    uvicorn.run("app.api:app", host="0.0.0.0", port=port)
