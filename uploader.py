import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")

if supabase_url and supabase_key:
    supabase: Client = create_client(supabase_url, supabase_key)
else:
    print("Warning: Supabase credentials not found in environment variables.")
    supabase = None

BUCKET_NAME = "panoramas"


def _content_type_for(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    return "application/octet-stream"


def upload_folder_to_supabase(local_folder_path: str, supabase_folder_path: str) -> str:
    """
    Upload all files in a local folder to a Supabase Storage bucket.
    Returns the public URL of the config.json file (used by the single-scene endpoint).
    """
    if not supabase:
        raise Exception("Supabase client not initialized. Missing credentials.")

    for root, _dirs, files in os.walk(local_folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, start=local_folder_path).replace("\\", "/")
            destination_path = f"{supabase_folder_path}/{relative_path}"

            with open(file_path, "rb") as f:
                supabase.storage.from_(BUCKET_NAME).upload(
                    path=destination_path,
                    file=file_path,
                    file_options={"content-type": _content_type_for(file), "upsert": "true"},
                )

    return supabase.storage.from_(BUCKET_NAME).get_public_url(f"{supabase_folder_path}/config.json")


def upload_folder_only(local_folder_path: str, supabase_folder_path: str) -> None:
    """Upload all files in a folder without returning a URL (used per-scene by the auto endpoint)."""
    if not supabase:
        raise Exception("Supabase client not initialized. Missing credentials.")

    for root, _dirs, files in os.walk(local_folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, start=local_folder_path).replace("\\", "/")
            destination_path = f"{supabase_folder_path}/{relative_path}"

            supabase.storage.from_(BUCKET_NAME).upload(
                path=destination_path,
                file=file_path,
                file_options={"content-type": _content_type_for(file), "upsert": "true"},
            )


def upload_bytes_to_supabase(data: bytes, destination_path: str, content_type: str = "application/octet-stream") -> str:
    """Upload raw bytes to a path in the panoramas bucket; returns the public URL."""
    if not supabase:
        raise Exception("Supabase client not initialized. Missing credentials.")

    supabase.storage.from_(BUCKET_NAME).upload(
        path=destination_path,
        file=data,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return supabase.storage.from_(BUCKET_NAME).get_public_url(destination_path)
