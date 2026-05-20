import os
import base64
import json
import re
import io
from typing import Optional

from PIL import Image
import anthropic

CLASSIFIER_MODEL = "claude-haiku-4-5"
DOOR_MODEL = "claude-haiku-4-5"

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; AI scene classification and door detection require it."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _encode_image(image_path: str, max_dim: int = 1024) -> tuple[str, str]:
    """Downsample image for vision calls so we stay well under per-image limits."""
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"


def _extract_json(text: str):
    match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in model response: {text[:200]}")
    return json.loads(match.group(0))


def classify_scene(image_path: str) -> dict:
    """Classify a 360 panorama into a room type. Returns {'label': str, 'title': str}."""
    client = _get_client()
    data, media_type = _encode_image(image_path)
    response = client.messages.create(
        model=CLASSIFIER_MODEL,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is an equirectangular 360 panorama of a room. Identify the room type. "
                            "Respond with ONLY a JSON object: "
                            '{"label": "snake_case_label", "title": "Human Readable Title"}. '
                            "Use labels like: main_room, bathroom, kitchen, bedroom, living_room, "
                            "dining_room, hallway, balcony, study, closet, laundry, garage, exterior."
                        ),
                    },
                ],
            }
        ],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    return _extract_json(text)


def detect_doors(image_path: str) -> list[dict]:
    """
    Detect doors / walkable openings in an equirectangular 360 panorama.
    Returns [{'pitch': float, 'yaw': float, 'description': str}, ...] in Pannellum's
    convention (yaw 0 = image center, positive yaw = right; pitch 0 = horizon, positive = up).
    """
    client = _get_client()
    data, media_type = _encode_image(image_path)
    response = client.messages.create(
        model=DOOR_MODEL,
        max_tokens=600,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is an equirectangular 360 panorama. Identify each visible door, doorway, "
                            "or large open passage a person could walk through. For each, give its position "
                            "as normalized coordinates in [0,1] where (0,0) is top-left and (1,1) is bottom-right, "
                            "using the BOTTOM-CENTER of the doorway. "
                            "Respond with ONLY a JSON array: "
                            '[{"x": 0.42, "y": 0.62, "description": "wooden door on left wall"}]. '
                            "Return [] if no clearly walkable openings are visible. "
                            "Do not include windows, mirrors, picture frames, or closed cabinet doors."
                        ),
                    },
                ],
            }
        ],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    raw = _extract_json(text)
    if not isinstance(raw, list):
        return []

    doors = []
    for d in raw:
        try:
            x = float(d["x"])
            y = float(d["y"])
        except (KeyError, ValueError, TypeError):
            continue
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            continue
        # Equirectangular -> Pannellum:
        #   x = 0.5 (image center) -> yaw 0 (forward)
        #   x = 1.0 (right edge)   -> yaw +180
        #   y = 0.5 (middle row)   -> pitch 0 (horizon)
        #   y = 1.0 (bottom)       -> pitch -90 (nadir)
        yaw = x * 360.0 - 180.0
        pitch = 90.0 - y * 180.0
        doors.append(
            {
                "pitch": round(pitch, 2),
                "yaw": round(yaw, 2),
                "description": d.get("description", "Doorway"),
            }
        )
    return doors
