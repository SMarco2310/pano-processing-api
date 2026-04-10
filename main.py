from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import uuid
from typing import Optional
import json

from processor import run_pannellum_generator, patch_hotspots
from uploader import upload_folder_to_supabase

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
    hotspots: Optional[str] = Form(None), # JSON string representation array of hotspot objects
    image: UploadFile = File(...)
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
            "tour_url": tour_url
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_image_path):
            os.remove(tmp_image_path)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)

@app.get("/health")
def health_check():
    return {"status": "ok"}
