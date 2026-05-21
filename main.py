from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import uuid
from typing import List, Optional
import json

from processor import run_pannellum_generator, patch_hotspots
from uploader import (
    upload_folder_to_supabase,
    upload_folder_only,
    upload_bytes_to_supabase,
)
from tour_builder import slugify, read_scene_base_config, build_tour_config
from ai import classify_scene, detect_doors

app = FastAPI(title="Pannellum Processing Microservice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("tmp", exist_ok=True)

# ==========================================
# OPTIMAL PANORAMIC IMAGE SPECIFICATIONS
# ==========================================
# For the clearest and most optimal virtual tours:
# 1. Aspect Ratio: MUST be exactly 2:1 (Width is exactly twice the Height).
# 2. Recommended Resolution: 8192x4096 (8K) for extremely sharp tours, or 4096x2048 (4K) for a great balance of quality and processing speed.
# 3. Format: Equirectangular projection (standard 360 camera output), JPEG or PNG.
# Note: Anything below 4K (e.g. 2048x1024) will look blurry when zoomed in.
# ==========================================
@app.post("/api/panorama/tour")
async def generate_tour(
    room_id: str = Form(...),
    hotspots: Optional[str] = Form(None),  # JSON string representation array of hotspot objects
    image: UploadFile = File(...),
):
    if not image.filename:
        raise HTTPException(status_code=400, detail="No valid file uploaded")

    hotspots_list = []
    if hotspots:
        try:
            hotspots_list = json.loads(hotspots)
        except Exception:
            raise HTTPException(status_code=400, detail="hotspots must be a valid JSON array")

    unique_id = uuid.uuid4().hex
    tmp_image_path = os.path.join("tmp", f"{unique_id}_{image.filename}")
    output_dir = os.path.join("tmp", f"output_{unique_id}")

    try:
        with open(tmp_image_path, "wb") as f:
            shutil.copyfileobj(image.file, f)

        success = run_pannellum_generator(tmp_image_path, output_dir)
        if not success:
            raise HTTPException(status_code=500, detail="Pannellum generation failed")

        if hotspots_list:
            config_path = os.path.join(output_dir, "config.json")
            patch_hotspots(config_path, hotspots_list)

        supabase_folder_path = f"{room_id}"
        tour_url = upload_folder_to_supabase(output_dir, supabase_folder_path)

        return {
            "status": "success",
            "room_id": room_id,
            "tour_url": tour_url,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_image_path):
            os.remove(tmp_image_path)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)


# ==========================================
# AUTOMATED MULTI-SCENE TOUR
# ==========================================
# Accepts N equirectangular images and produces a fully-linked Pannellum tour.
# Scene identification: uses provided scene_metadata when available, falls back to
#   Claude vision classification per image.
# Hotspot placement: uses Claude vision to detect walkable doors/openings in each
#   panorama and places navigation hotspots at the detected positions.
# ==========================================
@app.post("/api/panorama/tour/auto")
async def generate_tour_auto(
    tour_id: str = Form(...),
    scene_metadata: Optional[str] = Form(None),
    images: List[UploadFile] = File(...),
):
    """
    Build a multi-scene Pannellum tour from N uploaded panoramas.

    Form fields:
      - tour_id (required): unique id; used as the storage folder name.
      - images (required): one or more equirectangular .jpg/.png files.
      - scene_metadata (optional): JSON array, one entry per image, e.g.
          [{"filename": "img1.jpg", "label": "main_room", "title": "Main Room"}, ...]
        Any image without a matching entry is auto-classified via Claude vision.

    Returns:
      {"status": "success", "tour_id": ..., "tour_url": ..., "scenes": [...]}
    """
    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required")

    metadata_map = {}
    if scene_metadata:
        try:
            md = json.loads(scene_metadata)
            if not isinstance(md, list):
                raise ValueError("scene_metadata must be a JSON array")
            for entry in md:
                fn = entry.get("filename")
                if fn:
                    metadata_map[fn] = entry
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid scene_metadata: {e}")

    unique_id = uuid.uuid4().hex
    work_dir = os.path.join("tmp", f"auto_{unique_id}")
    os.makedirs(work_dir, exist_ok=True)

    try:
        # Stage 1: persist uploads, decide scene IDs (metadata first, AI fallback).
        scenes_meta = []
        used_ids = set()
        for image in images:
            if not image.filename:
                continue

            tmp_image_path = os.path.join(work_dir, image.filename)
            with open(tmp_image_path, "wb") as f:
                shutil.copyfileobj(image.file, f)

            entry = metadata_map.get(image.filename, {})
            label = entry.get("label")
            title = entry.get("title")

            if not label or not title:
                try:
                    classified = classify_scene(tmp_image_path)
                    label = label or classified.get("label") or "scene"
                    title = title or classified.get("title") or label.replace("_", " ").title()
                except Exception as e:
                    print(f"Scene classification failed for {image.filename}: {e}")
                    label = label or "scene"
                    title = title or "Scene"

            base_id = slugify(label)
            scene_id = base_id
            n = 2
            while scene_id in used_ids:
                scene_id = f"{base_id}_{n}"
                n += 1
            used_ids.add(scene_id)

            scenes_meta.append(
                {
                    "id": scene_id,
                    "title": title,
                    "filename": image.filename,
                    "image_path": tmp_image_path,
                }
            )

        if not scenes_meta:
            raise HTTPException(status_code=400, detail="No valid images in upload")

        # Stage 2: detect doors + run pannellum generator per scene.
        for scene in scenes_meta:
            try:
                scene["doors"] = detect_doors(scene["image_path"])
            except Exception as e:
                print(f"Door detection failed for {scene['filename']}: {e}")
                scene["doors"] = []

            scene_output = os.path.join(work_dir, f"scene_{scene['id']}")
            success = run_pannellum_generator(scene["image_path"], scene_output)
            if not success:
                raise HTTPException(
                    status_code=500,
                    detail=f"Pannellum generation failed for {scene['filename']}",
                )
            scene["output_dir"] = scene_output
            scene["base_config"] = read_scene_base_config(scene_output)
            scene["base_path"] = scene["id"]  # subfolder under tour_id/ in Supabase

        # Stage 3: assemble the tour config (cross-scene hotspots).
        tour_config = build_tour_config(scenes_meta)

        # Stage 4: upload per-scene tile folders, then the master tour_config.json.
        for scene in scenes_meta:
            upload_folder_only(scene["output_dir"], f"{tour_id}/{scene['id']}")

        tour_url = upload_bytes_to_supabase(
            json.dumps(tour_config, indent=2).encode("utf-8"),
            f"{tour_id}/tour_config.json",
            "application/json",
        )

        return {
            "status": "success",
            "tour_id": tour_id,
            "tour_url": tour_url,
            "scenes": [
                {
                    "id": s["id"],
                    "title": s["title"],
                    "filename": s["filename"],
                    "doors_detected": len(s["doors"]),
                }
                for s in scenes_meta
            ],
        }

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
