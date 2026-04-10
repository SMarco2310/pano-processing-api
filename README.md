# Pannellum Processing Microservice 📸

This is a standalone Python microservice built with **FastAPI**. It is designed to take high-resolution 360° equirectangular images, process them into multi-resolution image tiles (using the official Pannellum `generate.py` utility), inject navigation hotspots, and seamlessly upload the output directly to a **Supabase Storage** bucket.

By decoupling this heavy image-processing task from your main Node.js backend, your primary API remains fast, responsive, and easy to scale.

## 🚀 How it Works

1. **Upload Request**: Your frontend or main API sends a `POST` request to this service containing a 360° image file, a `room_id`, and optional `hotspots`.
2. **Tile Generation**: The microservice saves the image temporarily and executes the `generate.py` script. This script (powered by the OS tool `nona` from `hugin-tools`) chops the large panoramic image into a pyramid of smaller, optimized image "tiles".
3. **Hotspot Injection**: It automatically injects the navigation hotspots you provided into the resulting `config.json` configuration file.
4. **Cloud Sync**: Using the Supabase Python SDK, it uploads the entire nested folder of newly generated tiles (and the config) directly to your `panoramas` Supabase bucket.
5. **Response**: It immediately deletes the temporary local files to free up space and returns the public `tour_url` pointing to your new `config.json`, which your frontend Pannellum instance can instantly load!

## 📸 Optimal Panorama Image Rules
For the clearest virtual tours, images sent to this API should follow these specs:
- **Aspect Ratio**: MUST be exactly `2:1` (Width is exactly twice the Height).
- **Resolution**: `8192x4096 (8K)` or `4096x2048 (4K)` depending on desired quality vs processing speed. Anything below 4K will look blurry when zoomed in.
- **Format**: Equirectangular projection, JPEG or PNG.

## 💻 Local Development Setup

To test this locally on your machine:
**(Note: You must have Hugin installed on your PC so the script can access `nona`)**

1. Create a virtual environment and install the dependencies:
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
   ```
3. Start the FastAPI server:
   ```bash
   uvicorn main:app --reload
   ```

## 🌐 API Reference

### `POST /api/panorama/tour`
Accepts `multipart/form-data`.

**Parameters**:
- `room_id` (string, required): A unique identifier for the room. Used to structure the folder in Supabase.
- `image` (file, required): The 360° equirectangular photo.
- `hotspots` (string, optional): A JSON stringified array of hotspot objects to inject into the config.

**Success Response**:
```json
{
  "status": "success",
  "room_id": "lobby123",
  "tour_url": "https://your-project.supabase.co/storage/v1/object/public/panoramas/lobby123/config.json"
}
```

## 🐳 Deployment to Render

Because `generate.py` relies on the OS-level `hugin-tools` dependency, standard basic Python environments will fail. This project **requires Docker** to deploy so it can install `hugin-tools` flawlessly on a clean Linux container.

1. **Push to GitHub**: Commit this entire folder (including the provided `Dockerfile` and `render.yaml`).
2. **Go to Render**: In your dashboard, click **New > Blueprint**.
3. **Connect Repo**: Select this repository. Render will instantly read the `render.yaml` file.
4. **Environment Variables**: Fill out your Supabase URL and Key when prompted in the Render UI.
5. **Deploy**: Render will build the Docker container and start serving the API!
