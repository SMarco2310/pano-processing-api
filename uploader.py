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

def upload_folder_to_supabase(local_folder_path: str, supabase_folder_path: str) -> str:
    """
    Uploads all files in a local folder to a Supabase Storage bucket.
    Returns the public URL of the config.json file.
    """
    if not supabase:
        raise Exception("Supabase client not initialized. Missing credentials.")

    bucket_name = "panoramas"
    
    for root, dirs, files in os.walk(local_folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            # Calculate the relative path for Supabase
            relative_path = os.path.relpath(file_path, start=local_folder_path)
            
            # Make sure to use forward slashes for supabase storage paths
            relative_path = relative_path.replace("\\", "/")
            destination_path = f"{supabase_folder_path}/{relative_path}"
            
            # Set content type based on extension
            content_type = "application/octet-stream"
            if file.endswith(".json"):
                content_type = "application/json"
            elif file.endswith(".jpg") or file.endswith(".jpeg"):
                content_type = "image/jpeg"
            elif file.endswith(".png"):
                content_type = "image/png"
            
            with open(file_path, "rb") as f:        
                supabase.storage.from_(bucket_name).upload(
                    path=destination_path, 
                    file=file_path,
                    file_options={"content-type": content_type, "upsert": "true"}
                )
    
    # Return the public URL to the config.json
    res = supabase.storage.from_(bucket_name).get_public_url(f"{supabase_folder_path}/config.json")
    return res
