import os
from typing import Optional

import httpx


def is_configured() -> bool:
    return bool(os.environ.get("CONVEX_STORAGE_URL"))


async def upload_tour_config(tour_config: dict, tour_id: str) -> dict:
    """
    Upload tour_config JSON to Convex storage via a customer-provided HTTP action.

    Returns {'url': str, 'storage_id': str}.

    The CampusNest Convex backend must expose an HTTP action at CONVEX_STORAGE_URL
    that:
      1. Accepts POST with `Content-Type: application/json` and optionally
         `Authorization: Bearer <CONVEX_STORAGE_TOKEN>`.
      2. Verifies the shared secret.
      3. Stores the supplied tour_config via `ctx.storage.store(blob)`.
      4. Returns `{ "storageId": "...", "url": "..." }`.

    A copy-pasteable implementation lives in the README under "Convex storage
    integration".
    """
    url = os.environ.get("CONVEX_STORAGE_URL")
    if not url:
        raise RuntimeError("CONVEX_STORAGE_URL is not set")

    token: Optional[str] = os.environ.get("CONVEX_STORAGE_TOKEN")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {"tour_id": tour_id, "tour_config": tour_config}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if "url" not in data:
        raise RuntimeError(
            f"Convex action response missing 'url' field: {data}"
        )

    return {"url": data["url"], "storage_id": data.get("storageId", "")}
