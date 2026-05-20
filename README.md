# Automated Room Tour API (equirectangular)

A tiny FastAPI service that turns N uploaded 360 panoramas into a fully-linked Pannellum tour config, with **AI-driven room classification and door detection**. No tiling, no `hugin-tools`, no storage layer.

## How it works

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

```bash
python -m venv venv
source venv/bin/activate   # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env       # then fill in keys
uvicorn main:app --reload
```

## Deployment

No Docker, no system packages. Any Python 3.10+ host works — Render, Railway, Fly, Vercel (with the Python runtime), Cloud Run, a $5 VPS.

A minimal Render config:
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

## Notes on accuracy

- **Room classification**: Groq's Llama 4 Scout is very reliable here. Claude is marginally better but not worth the cost for this step.
- **Door detection**: this is the harder task. Llama models will occasionally flag a window, mirror, or large painting as a door, and the bottom-center coordinates may be a few degrees off. If a particular tour matters, send it again with `vision_provider: "claude"` for a cleaner pass.
- The service falls through gracefully if AI fails: classification falls back to `"scene"`/`"Scene"`, door detection falls back to an empty list (and each scene gets one fallback hotspot at the horizon).
