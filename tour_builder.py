import json
import os
import re


def slugify(label: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", (label or "").lower().strip())
    return re.sub(r"_+", "_", s).strip("_") or "scene"


def read_scene_base_config(scene_output_dir: str) -> dict:
    """Read the per-scene config.json produced by Pannellum's generate.py."""
    config_path = os.path.join(scene_output_dir, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Pannellum config not found at {config_path}")
    with open(config_path) as f:
        return json.load(f)


def _build_hotspots_for_scene(scene_index: int, scenes: list[dict]) -> list[dict]:
    """
    Distribute detected doors as scene-link hotspots.
    Each door in this scene targets the next scene in the ring; extra doors cycle through
    the remaining scenes. Scenes with no detected doors get a fallback hotspot at horizon center.
    """
    this_scene = scenes[scene_index]
    others = [s for i, s in enumerate(scenes) if i != scene_index]
    if not others:
        return []

    doors = this_scene.get("doors") or []
    if not doors:
        target = others[0]
        return [
            {
                "pitch": -10,
                "yaw": 0,
                "type": "scene",
                "text": f"Go to {target['title']}",
                "sceneId": target["id"],
            }
        ]

    hotspots = []
    for i, door in enumerate(doors):
        target = others[i % len(others)]
        hotspots.append(
            {
                "pitch": door["pitch"],
                "yaw": door["yaw"],
                "type": "scene",
                "text": f"Go to {target['title']}",
                "sceneId": target["id"],
            }
        )
    return hotspots


def _build_scene_entry(scene_id: str, title: str, base_config: dict,
                       base_path: str, hotspots: list[dict]) -> dict:
    entry = {
        "title": title,
        "type": base_config.get("type", "multires"),
        "hfov": base_config.get("hfov", 100),
        "hotSpots": hotspots,
    }
    if "multiRes" in base_config:
        multi = dict(base_config["multiRes"])
        multi["basePath"] = base_path
        entry["multiRes"] = multi
    elif "panorama" in base_config:
        entry["panorama"] = base_path
    return entry


def build_tour_config(scenes: list[dict]) -> dict:
    """
    Build a multi-scene Pannellum tour config.

    Each scene dict requires:
      - id (str, unique slug)
      - title (str, human-readable)
      - base_config (dict, parsed from Pannellum's per-scene config.json)
      - base_path (str, folder path relative to the tour_config.json location)
      - doors (list of {pitch, yaw, description})
    """
    if not scenes:
        raise ValueError("At least one scene is required")

    config = {
        "default": {
            "firstScene": scenes[0]["id"],
            "author": "pano-processing-api",
            "sceneFadeDuration": 1000,
        },
        "scenes": {},
    }
    for i, scene in enumerate(scenes):
        config["scenes"][scene["id"]] = _build_scene_entry(
            scene_id=scene["id"],
            title=scene["title"],
            base_config=scene["base_config"],
            base_path=scene["base_path"],
            hotspots=_build_hotspots_for_scene(i, scenes),
        )
    return config
