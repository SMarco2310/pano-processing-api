# Automated Room Tour API (equirectangular)

A tiny FastAPI service that turns N uploaded 360 panoramas into a fully-linked Pannellum tour config, with **AI-driven room classification and door detection**. No tiling, no `hugin-tools`, no storage layer.

---

## Two versions of this service

This repo has two parallel implementations on separate branches. Pick the one that matches your needs.

| | **Equirectangular** *(this branch)* | **Tiling / multires** *([`claude/automate-room-tour-system-jJhkK`](https://github.com/SMarco2310/pano-processing-api/tree/claude/automate-room-tour-system-jJhkK))* |
|---|---|---|
| **Pannellum mode** | `equirectangular` — one .jpg per scene | `multires` — pyramid of small tiles per scene |
| **Files per scene in storage** | 1 (the original .jpg) | 30–100+ tile files + a config.json |
| **Browser load** | Downloads the whole .jpg upfront | Lazy-loads only tiles in view, low-res fallback shows instantly |
| **Best for** | Up to 4K, normal connections, small tours | 8K+ images, slow connections, gallery-grade tours |
| **Input** | JSON with public image URLs | Multipart upload of raw image files |
| **Output** | Returns `tour_config` JSON inline (you persist it) | Uploads tiles + config to Supabase, returns `tour_url` |
| **Storage owner** | The caller (Convex / R2 / wherever you put the images) | The service (Supabase bucket `panoramas`) |
| **Vision provider** | Groq (free) by default, Claude opt-in | Claude only |
| **AI cost per tour** | $0 with Groq, ~$0.015 with Claude | ~$0.015 |
| **System dependencies** | None — plain Python 3.10+ | `hugin-tools` |
| **Deploy targets** | Any Python host, or Docker | Render with Docker (free tier works) |
| **Stateful?** | No — stateless request/response | Yes — writes to Supabase |

**Default recommendation for CampusNest-style apps:** equirectangular (this branch). The tiling branch is there if you decide you need 8K+ source images or want to optimize bandwidth for users on bad connections.

---

## How this (equirectangular) version works

1. Your app uploads equirectangular .jpgs to your own storage (Convex, R2, S3, etc.) and gets public URLs.
2. You `POST` those URLs to this API along with a `tour_id`.
3. For each image, the service:
   - downloads it to a temp directory,
   - uses **Groq** (free) or **Claude** vision to identify the room type (when you don't provide a label),
   - uses the same vision model to detect walkable doors / openings and converts pixel positions to Pannellum pitch/yaw,
   - deletes the temp copy.
4. Returns a fully-assembled multi-scene `tour_config` JSON with scenes linked through the detected doors.
5. Your app persists the returned `tour_config` wherever it likes (Convex storage, a DB field, etc.).

**This service is stateless.** It never stores your images, your tour configs, or anything else. The temp files only exist during the few seconds of one request.

## API

### `POST /api/panorama/tour/auto`

**Request body** (JSON):
```json
{
  "tour_id": "room_42",
  "vision_provider": "groq",
  "scenes": [
    {
      "image_url": "https://your-convex.../main.jpg",
      "filename": "main.jpg",
      "label": "main_room",
      "title": "Main Room"
    },
    {
      "image_url": "https://your-convex.../bath.jpg"
    }
  ]
}
```

- `tour_id` (required): an opaque id you control, echoed back in the response.
- `scenes[].image_url` (required): a public URL the service can `GET`.
- `scenes[].label` / `scenes[].title` (optional): provide them to skip AI classification for that scene.
- `vision_provider` (optional, default `"groq"`): `"groq"` is free; `"claude"` is more accurate at door localization.

**Response**:
```json
{
  "status": "success",
  "tour_id": "room_42",
  "vision_provider": "groq",
  "tour_config": {
    "default": { "firstScene": "main_room", "sceneFadeDuration": 1000 },
    "scenes": {
      "main_room": {
        "type": "equirectangular",
        "panorama": "https://your-convex.../main.jpg",
        "title": "Main Room",
        "hfov": 100,
        "hotSpots": [
          { "type": "scene", "pitch": -5, "yaw": 117, "text": "Go to Bathroom", "sceneId": "bathroom" }
        ]
      },
      "bathroom": { ... }
    }
  },
  "scenes": [
    { "id": "main_room", "title": "Main Room", "filename": "main.jpg", "image_url": "...", "doors_detected": 1 },
    { "id": "bathroom",  "title": "Bathroom",  "filename": "bath.jpg", "image_url": "...", "doors_detected": 1 }
  ]
}
```

Feed `tour_config` straight into Pannellum:

```js
pannellum.viewer('viewer', { config: tour_config });
```

### `GET /health`
Returns `{"status": "ok"}`.

## Environment variables

| Variable            | Required for      | Notes                                                  |
| ------------------- | ----------------- | ------------------------------------------------------ |
| `GROQ_API_KEY`      | `vision_provider="groq"`  | Free at console.groq.com — generous free tier         |
| `ANTHROPIC_API_KEY` | `vision_provider="claude"` | Paid; ~$0.003 per scene for door detection             |

You only need the key(s) for the provider(s) you actually use.

## Local development

### Plain Python

```bash
python -m venv venv
source venv/bin/activate   # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env       # then fill in keys
uvicorn main:app --reload
```

### Docker

```bash
docker build -t pano-tour-api .
docker run -p 10000:10000 --env-file .env pano-tour-api
```

The API is then available at `http://localhost:10000`.

## Deployment

This branch has no OS-level dependencies, so you have two deployment paths.

### Plain Python runtime (lightest)

Any Python 3.10+ host works — Render, Railway, Fly, Vercel (Python runtime), Cloud Run, a $5 VPS. The provided `render.yaml` uses this path:

```yaml
services:
  - type: web
    name: pano-tour-api
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: GROQ_API_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
```

### Docker (matches the tiling branch's deploy story)

The included `Dockerfile` is a minimal `python:3.11-slim` image. Useful if you want one consistent deploy pipeline for both branches, or are deploying somewhere that requires a container (Cloud Run, ECS, Kubernetes, Fly Machines).

To deploy this branch on Render via Docker instead of the Python runtime, swap `render.yaml` to:

```yaml
services:
  - type: web
    name: pano-tour-api
    env: docker
    plan: free
    envVars:
      - key: GROQ_API_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
```

## Notes on accuracy

- **Room classification**: Groq's Llama 4 Scout is very reliable here. Claude is marginally better but not worth the cost for this step.
- **Door detection**: this is the harder task. Llama models will occasionally flag a window, mirror, or large painting as a door, and the bottom-center coordinates may be a few degrees off. If a particular tour matters, send it again with `vision_provider: "claude"` for a cleaner pass.
- The service falls through gracefully if AI fails: classification falls back to `"scene"`/`"Scene"`, door detection falls back to an empty list (and each scene gets one fallback hotspot at the horizon).
