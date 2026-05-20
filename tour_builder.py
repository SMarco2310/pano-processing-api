import re


def slugify(label: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", (label or "").lower().strip())
    return re.sub(r"_+", "_", s).strip("_") or "scene"


def _build_hotspots(scene_index: int, scenes: list[dict]) -> list[dict]:
    """
    Distribute detected doors as scene-link hotspots.
    Each door targets the next scene in the ring; extra doors cycle through.
    Scenes with no detected doors get a fallback hotspot at horizon center.
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


def build_tour_config(scenes: list[dict]) -> dict:
    """
    Build a multi-scene Pannellum equirectangular tour config.

    Each scene dict requires:
      - id (str, unique slug)
      - title (str, human-readable)
      - image_url (str, public URL to the equirectangular .jpg)
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
        config["scenes"][scene["id"]] = {
            "title": scene["title"],
            "type": "equirectangular",
            "panorama": scene["image_url"],
            "hfov": 100,
            "hotSpots": _build_hotspots(i, scenes),
        }
    return config
