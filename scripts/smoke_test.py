"""60-second check that the workspace + token can reach a live serving endpoint.

Run:  DATABRICKS_HOST=... DATABRICKS_TOKEN=... python scripts/smoke_test.py
"""
import os

from databricks.sdk import WorkspaceClient


def main() -> None:
    w = WorkspaceClient()
    client = w.serving_endpoints.get_open_ai_client()
    model = os.environ.get("TIER1_MODEL", "databricks-gemini-3-5-flash")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
    )
    print(model, "->", resp.choices[0].message.content)


if __name__ == "__main__":
    main()
