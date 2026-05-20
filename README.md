# Pannellum Processing Microservice

This is a standalone Python microservice built with **FastAPI**. It takes high-resolution 360 equirectangular images, processes them into multi-resolution image tiles (using the official Pannellum `generate.py` utility), and uploads the output to a **Supabase Storage** bucket.

It offers two flows:

1. **Single-scene** (`/api/panorama/tour`): you supply one image + (optional) hotspots, you get one Pannellum config back.
2. **Automated multi-scene** (`/api/panorama/tour/auto`): you supply N images, the service uses Claude vision to identify each room and detect walkable doorways, then builds and uploads a fully-linked multi-scene `tour_config.json`.

## How it works (automated flow)

1. **Upload**: your frontend or main API sends a multipart `POST` with a `tour_id` and one or more equirectangular images.
2. **Scene identification**: for each image, the service uses any `scene_metadata` you provided; missing labels are auto-classified by Claude vision (room type -> snake_case label + title).
3. **Door detection**: Claude vision detects walkable doors/openings in each panorama and returns normalized coordinates, which the service converts to Pannellum pitch/yaw.
4. **Tile generation**: the official Pannellum `generate.py` (backed by `nona` from `hugin-tools`) produces a tile pyramid per scene.
5. **Tour assembly**: scenes are linked in a ring; each detected door becomes a navigation hotspot pointing to the next scene in the ring. Scenes with no detected doors get a fallback hotspot.
6. **Upload**: tiles upload to `panoramas/{tour_id}/{scene_id}/...`; the master `tour_config.json` uploads to `panoramas/{tour_id}/tour_config.json` and its public URL is returned.

## Optimal Panorama Image Rules
For the clearest virtual tours, images sent to this API should follow these specs:
- **Aspect Ratio**: MUST be exactly `2:1` (width is exactly twice the height).
- **Resolution**: `8192x4096 (8K)` or `4096x2048 (4K)`. Anything below 4K will look blurry when zoomed in.
- **Format**: Equirectangular projection, JPEG or PNG.

## Local Development Setup

**(Note: you must have Hugin installed locally so `scripts/generate.py` can call `nona`.)**

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   # Windows
   .\venv\Scripts\activate
   # Mac/Linux
   source venv/bin/activate

   pip install -r requirements.txt
   ```
2. Create a `.env` file in the root directory:
   ```env
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-supabase-service-role-key
   ANTHROPIC_API_KEY=sk-ant-...   # required only for the automated /tour/auto endpoint
   ```
3. Start the FastAPI server:
   ```bash
   uvicorn main:app --reload
   ```

## API Reference

### `POST /api/panorama/tour`
Single-scene endpoint. Accepts `multipart/form-data`.

**Parameters**:
- `room_id` (string, required): unique identifier; used as the folder name in Supabase.
- `image` (file, required): the 360 equirectangular photo.
- `hotspots` (string, optional): JSON-stringified array of hotspot objects to inject into the config.

**Success Response**:
```json
{
  "status": "success",
  "room_id": "lobby123",
  "tour_url": "https://your-project.supabase.co/storage/v1/object/public/panoramas/lobby123/config.json"
}
```

### `POST /api/panorama/tour/auto`
Automated multi-scene endpoint. Accepts `multipart/form-data`.

**Parameters**:
- `tour_id` (string, required): unique identifier; used as the folder name in Supabase.
- `images` (file[], required): one or more equirectangular .jpg/.png files. Repeat the field for each image.
- `scene_metadata` (string, optional): JSON-stringified array of `{filename, label, title}` objects matched by filename. Any image without a matching entry is auto-classified.

**Example `scene_metadata`**:
```json
[
  {"filename": "img_1.jpg", "label": "main_room", "title": "Main Room"},
  {"filename": "img_2.jpg", "label": "bathroom",  "title": "Bathroom"}
]
```

**Success Response**:
```json
{
  "status": "success",
  "tour_id": "flat-42",
  "tour_url": "https://your-project.supabase.co/storage/v1/object/public/panoramas/flat-42/tour_config.json",
  "scenes": [
    {"id": "main_room", "title": "Main Room", "filename": "img_1.jpg", "doors_detected": 2},
    {"id": "bathroom",  "title": "Bathroom",  "filename": "img_2.jpg", "doors_detected": 1}
  ]
}
```

Point your frontend Pannellum viewer at `tour_url` and it will load the full multi-scene tour:
```js
pannellum.viewer('viewer', { config: '<tour_url>' });
```

## Deployment to Render

Because `generate.py` depends on the OS-level `hugin-tools` package, this project deploys via Docker.

1. **Push to GitHub**: commit this folder (including the provided `Dockerfile` and `render.yaml`).
2. **Go to Render**: in the dashboard, click **New > Blueprint**.
3. **Connect repo**: select this repository. Render reads `render.yaml`.
4. **Environment variables**: fill in `SUPABASE_URL`, `SUPABASE_KEY`, and `ANTHROPIC_API_KEY` when prompted.
5. **Deploy**: Render builds the Docker container and starts serving the API.
