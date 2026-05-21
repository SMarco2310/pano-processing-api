from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import uuid
import tempfile
import shutil
import httpx

from ai import classify_scene, detect_doors, VisionProvider
from tour_builder import slugify, build_tour_config
import convex_storage

app = FastAPI(title="Automated Room Tour API (equirectangular)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SceneInput(BaseModel):
    image_url: str = Field(..., description="Public URL to the equirectangular .jpg/.png")
    filename: Optional[str] = None
    label: Optional[str] = Field(None, description="Optional snake_case room label; AI fallback if missing")
    title: Optional[str] = Field(None, description="Optional human-readable scene title; AI fallback if missing")


class TourRequest(BaseModel):
    tour_id: str
    scenes: List[SceneInput]
    vision_provider: Optional[str] = Field("groq", description="'groq' (default, free) or 'claude' (more accurate)")
    upload_to_convex: Optional[bool] = Field(
        None,
        description=(
            "If true, upload the resulting tour_config to Convex storage and return its URL. "
            "Defaults to true when CONVEX_STORAGE_URL is configured, false otherwise. "
            "Set explicitly to override the default."
        ),
    )


@app.post("/api/panorama/tour/auto")
async def generate_tour_auto(req: TourRequest):
    """
    Build a multi-scene Pannellum equirectangular tour from N image URLs.

    Input: tour_id + array of scenes (each with image_url, optional label/title).
    Output: tour_config object ready to feed to Pannellum + per-scene metadata.

    When CONVEX_STORAGE_URL is configured (and upload_to_convex is not explicitly
    false), the assembled tour_config is also uploaded to Convex storage via the
    customer's HTTP action; the resulting public URL is returned as tour_url.
    """
    if not req.scenes:
        raise HTTPException(status_code=400, detail="At least one scene is required")

    try:
        provider = VisionProvider(req.vision_provider or "groq")
    except ValueError:
        raise HTTPException(status_code=400, detail="vision_provider must be 'groq' or 'claude'")

    work_dir = os.path.join(tempfile.gettempdir(), f"tour_{uuid.uuid4().hex}")
    os.makedirs(work_dir, exist_ok=True)

    try:
        scenes_meta = []
        used_ids = set()

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as http:
            for i, scene in enumerate(req.scenes):
                filename = scene.filename or f"scene_{i}.jpg"
                local_path = os.path.join(work_dir, filename)

                try:
                    resp = await http.get(scene.image_url)
                    resp.raise_for_status()
                except Exception as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to download {scene.image_url}: {e}",
                    )
                with open(local_path, "wb") as f:
                    f.write(resp.content)

                # Scene label/title: metadata first, AI fallback.
                label = scene.label
                title = scene.title
                if not label or not title:
                    try:
                        classified = classify_scene(local_path, provider)
                        label = label or classified.get("label") or "scene"
                        title = title or classified.get("title") or label.replace("_", " ").title()
                    except Exception as e:
                        print(f"Scene classification failed for {filename}: {e}")
                        label = label or "scene"
                        title = title or "Scene"

                base_id = slugify(label)
                scene_id = base_id
                n = 2
                while scene_id in used_ids:
                    scene_id = f"{base_id}_{n}"
                    n += 1
                used_ids.add(scene_id)

                try:
                    doors = detect_doors(local_path, provider)
                except Exception as e:
                    print(f"Door detection failed for {filename}: {e}")
                    doors = []

                scenes_meta.append(
                    {
                        "id": scene_id,
                        "title": title,
                        "filename": filename,
                        "image_url": scene.image_url,
                        "doors": doors,
                    }
                )

        tour_config = build_tour_config(scenes_meta)

        response = {
            "status": "success",
            "tour_id": req.tour_id,
            "vision_provider": provider.value,
            "tour_config": tour_config,
            "scenes": [
                {
                    "id": s["id"],
                    "title": s["title"],
                    "filename": s["filename"],
                    "image_url": s["image_url"],
                    "doors_detected": len(s["doors"]),
                }
                for s in scenes_meta
            ],
        }

        # Optionally persist the tour_config to Convex storage.
        should_upload = req.upload_to_convex if req.upload_to_convex is not None else convex_storage.is_configured()
        if should_upload:
            if not convex_storage.is_configured():
                raise HTTPException(
                    status_code=500,
                    detail="upload_to_convex=true but CONVEX_STORAGE_URL is not configured on the server",
                )
            try:
                upload = await convex_storage.upload_tour_config(tour_config, req.tour_id)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Convex storage upload failed: {e}")
            response["tour_url"] = upload["url"]
            response["storage_id"] = upload["storage_id"]

        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)


@app.get("/health")
def health_check():
    return {"status": "ok"}
