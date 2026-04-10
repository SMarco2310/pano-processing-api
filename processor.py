import subprocess
import os
import json

def run_pannellum_generator(input_image_path: str, output_dir: str):
    """
    Runs the official Pannellum generate.py script on the equirectangular image.
    """
    print(f"Running Pannellum on {input_image_path} -> {output_dir}")
    # Always ensure to use the current python environment
    import sys
    python_executable = sys.executable

    try:
        result = subprocess.run(
            [python_executable, "scripts/generate.py", input_image_path, "-o", output_dir],
            check=True,
            capture_output=True,
            text=True
        )
        print("Pannellum output:", result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("Error during panorama generation:", e)
        print("Stderr:", e.stderr)
        print("Stdout:", e.stdout)
        return False

def patch_hotspots(config_path: str, hotspots: list):
    """
    Injects scene/hotspot definitions into the generated config.json.
    """
    if not os.path.exists(config_path):
        print(f"Cannot patch hotspots: {config_path} not found.")
        return False
        
    print(f"Patching hotspots into {config_path}")
    with open(config_path, 'r+') as file:
        data = json.load(file)
        
        data["hotSpots"] = hotspots
        
        file.seek(0)
        json.dump(data, file, indent=4)
        file.truncate()
        
    return True
