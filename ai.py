import os
import base64
import json
import re
import io
from enum import Enum
from typing import Optional

from PIL import Image
import anthropic
from groq import Groq

CLAUDE_MODEL = "claude-haiku-4-5"
# Groq's Llama 4 Scout has strong vision and is free-tier eligible.
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


class VisionProvider(str, Enum):
    GROQ = "groq"
    CLAUDE = "claude"


_anthropic_client: Optional[anthropic.Anthropic] = None
_groq_client: Optional[Groq] = None


def _get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _anthropic_client = anthropic.Anthropic(api_key=key)
    return _anthropic_client


def _get_groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set")
        _groq_client = Groq(api_key=key)
    return _groq_client


def _encode_image(image_path: str, max_dim: int = 1024) -> tuple[str, str]:
    """Downsample for vision calls so we stay under per-image size limits."""
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


CLASSIFY_PROMPT = (
    "This is an equirectangular 360 panorama of a room. Identify the room type. "
    "Respond with ONLY a JSON object: "
    '{"label": "snake_case_label", "title": "Human Readable Title"}. '
    "Use labels like: main_room, bathroom, kitchen, bedroom, living_room, "
    "dining_room, hallway, balcony, study, closet, laundry, garage, exterior."
)

DOORS_PROMPT = (
    "This is an equirectangular 360 panorama. Identify each visible door, doorway, "
    "or large open passage a person could walk through. For each, give its position "
    "as normalized coordinates in [0,1] where (0,0) is top-left and (1,1) is bottom-right, "
    "using the BOTTOM-CENTER of the doorway. "
    "Respond with ONLY a JSON array: "
    '[{"x": 0.42, "y": 0.62, "description": "wooden door on left wall"}]. '
    "Return [] if no clearly walkable openings are visible. "
    "Do not include windows, mirrors, picture frames, or closed cabinet doors."
)


def _claude_vision(image_path: str, prompt: str, max_tokens: int) -> str:
    client = _get_anthropic()
    data, media = _encode_image(image_path)
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media, "data": data},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return next((b.text for b in resp.content if b.type == "text"), "")


def _groq_vision(image_path: str, prompt: str, max_tokens: int) -> str:
    client = _get_groq()
    data, media = _encode_image(image_path)
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media};base64,{data}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return resp.choices[0].message.content or ""


def _run_vision(image_path: str, prompt: str, max_tokens: int, provider: VisionProvider) -> str:
    if provider == VisionProvider.CLAUDE:
        return _claude_vision(image_path, prompt, max_tokens)
    return _groq_vision(image_path, prompt, max_tokens)


def classify_scene(image_path: str, provider: VisionProvider = VisionProvider.GROQ) -> dict:
    """Classify a 360 panorama into a room type. Returns {'label': str, 'title': str}."""
    text = _run_vision(image_path, CLASSIFY_PROMPT, 300, provider)
    return _extract_json(text)


def detect_doors(image_path: str, provider: VisionProvider = VisionProvider.GROQ) -> list[dict]:
    """
    Detect walkable openings in an equirectangular 360 panorama.
    Returns [{'pitch': float, 'yaw': float, 'description': str}, ...] in Pannellum's
    convention: yaw 0 = image center, positive yaw = right; pitch 0 = horizon, positive = up.
    """
    text = _run_vision(image_path, DOORS_PROMPT, 600, provider)
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
        #   x = 0.5 (image center) -> yaw 0; x = 1.0 -> yaw +180
        #   y = 0.5 (horizon row)  -> pitch 0; y = 1.0 -> pitch -90 (nadir)
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
