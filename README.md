# Automated Room Tour API (equirectangular)

A tiny FastAPI service that turns N uploaded 360 panoramas into a fully-linked Pannellum tour config, with **AI-driven room classification and door detection** and **optional Convex storage** for the resulting `tour_config.json`.

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
| **Output** | Returns `tour_config` JSON inline + optionally uploads it to **Convex storage** | Uploads tiles + config to **Supabase**, returns `tour_url` |
| **Storage** | Images: your storage (Convex/R2/…). tour_config: Convex (optional). | Both: Supabase bucket `panoramas` |
| **Vision provider** | Groq (free) by default, Claude opt-in | Claude only |
| **AI cost per tour** | $0 with Groq, ~$0.015 with Claude | ~$0.015 |
| **System dependencies** | None — plain Python 3.10+ | `hugin-tools` |
| **Deploy targets** | Any Python host, or Docker | Render with Docker (free tier works) |
| **Stateful?** | Only when CONVEX_STORAGE_URL is set | Yes — writes to Supabase |

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
4. Builds a multi-scene `tour_config` JSON with scenes linked through the detected doors.
5. If Convex storage is configured, uploads the `tour_config` to your Convex deployment and returns the resulting `tour_url`. Otherwise the `tour_config` is returned inline for the caller to persist.

**The service holds no state across requests.** Even with Convex storage enabled, the temp image files exist only for the few seconds of a single request — the upload goes to *your* Convex deployment, not to the API server.

## API

### `POST /api/panorama/tour/auto`

**Request body** (JSON):
```json
{
  "tour_id": "room_42",
  "vision_provider": "groq",
  "upload_to_convex": true,
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
- `scenes[].label` / `scenes[].title` (optional): skip AI classification for that scene.
- `vision_provider` (optional, default `"groq"`): `"groq"` is free; `"claude"` is more accurate at door localization.
- `upload_to_convex` (optional): explicitly enable/disable the Convex upload step. Defaults to `true` when `CONVEX_STORAGE_URL` is configured on the server, `false` otherwise.

**Response** (with Convex storage enabled):
```json
{
  "status": "success",
  "tour_id": "room_42",
  "vision_provider": "groq",
  "tour_url": "https://abc-123.convex.cloud/api/storage/...",
  "storage_id": "kg2...",
  "tour_config": { "default": { ... }, "scenes": { ... } },
  "scenes": [
    { "id": "main_room", "title": "Main Room", "filename": "main.jpg", "image_url": "...", "doors_detected": 1 },
    { "id": "bathroom",  "title": "Bathroom",  "filename": "bath.jpg", "image_url": "...", "doors_detected": 1 }
  ]
}
```

Feed the `tour_url` to Pannellum (it will fetch the JSON), or skip the URL hop and pass `tour_config` directly:

```js
// Either of these works
pannellum.viewer('viewer', { config: tour_url });
pannellum.viewer('viewer', { config: tour_config });
```

### `GET /health`
Returns `{"status": "ok"}`.

## Environment variables

| Variable                | Required for                | Notes                                                  |
| ----------------------- | --------------------------- | ------------------------------------------------------ |
| `GROQ_API_KEY`          | `vision_provider="groq"`    | Free at console.groq.com — generous free tier         |
| `ANTHROPIC_API_KEY`     | `vision_provider="claude"`  | Paid; ~$0.003 per scene for door detection             |
| `CONVEX_STORAGE_URL`    | Convex storage uploads      | Your CampusNest HTTP action URL (see next section)     |
| `CONVEX_STORAGE_TOKEN`  | Convex storage uploads      | Shared secret matching the one your Convex action expects |

You only need the vision key(s) for the provider(s) you actually use. The Convex variables are optional — leave them blank to use the stateless mode.

---

## Convex storage integration

For Convex to accept uploads from this API, add a small HTTP action to your CampusNest Convex backend that stores the `tour_config` and returns its public URL.

### 1. Add the HTTP action to CampusNest

Create or extend `convex/http.ts`:

```ts
import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";

const http = httpRouter();

http.route({
  path: "/api/store-tour-config",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    // Verify shared secret
    const auth = request.headers.get("Authorization");
    const expected = `Bearer ${process.env.PANO_API_SHARED_SECRET}`;
    if (auth !== expected) {
      return new Response("Unauthorized", { status: 401 });
    }

    const body = await request.json();
    const blob = new Blob(
      [JSON.stringify(body.tour_config)],
      { type: "application/json" }
    );
    const storageId = await ctx.storage.store(blob);
    const url = await ctx.storage.getUrl(storageId);

    // Optional: persist the storageId on the room here if you want.
    // e.g. await ctx.runMutation(internal.rooms.setTourConfig, { tourId: body.tour_id, storageId, url });

    return new Response(JSON.stringify({ storageId, url }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }),
});

export default http;
```

### 2. Set the shared secret on the Convex side

In the Convex dashboard for your CampusNest deployment, set the environment variable:
```
PANO_API_SHARED_SECRET=<some-long-random-string>
```

### 3. Configure the pano API

In this service's environment (Render dashboard or `.env` for local dev):
```
CONVEX_STORAGE_URL=https://<your-convex-deployment>.convex.site/api/store-tour-config
CONVEX_STORAGE_TOKEN=<the-same-long-random-string>
```

Your Convex deployment URL ends in `.convex.site` for HTTP actions (note: **not** `.convex.cloud`, which is the WebSocket endpoint for queries/mutations).

That's it. Once both env vars are set, every request to `/api/panorama/tour/auto` automatically uploads the assembled `tour_config` to Convex and includes `tour_url` + `storage_id` in the response.

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

Any Python 3.10+ host works — Render, Railway, Fly, Vercel (Python runtime), Cloud Run, a $5 VPS. The provided `render.yaml` uses this path and already declares the Convex env vars.

### Docker

The included `Dockerfile` is a minimal `python:3.11-slim` image. Useful if you want one consistent deploy pipeline for both branches, or are deploying somewhere that requires a container (Cloud Run, ECS, Kubernetes, Fly Machines).

To deploy via Docker on Render, swap `render.yaml` to:

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
      - key: CONVEX_STORAGE_URL
        sync: false
      - key: CONVEX_STORAGE_TOKEN
        sync: false
```

## Notes on accuracy

- **Room classification**: Groq's Llama 4 Scout is very reliable here. Claude is marginally better but not worth the cost for this step.
- **Door detection**: this is the harder task. Llama models will occasionally flag a window, mirror, or large painting as a door, and the bottom-center coordinates may be a few degrees off. If a particular tour matters, send it again with `vision_provider: "claude"` for a cleaner pass.
- The service falls through gracefully if AI fails: classification falls back to `"scene"`/`"Scene"`, door detection falls back to an empty list (and each scene gets one fallback hotspot at the horizon).
