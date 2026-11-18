"""OpenAI calls: the project story (names + architect-report prose) and the render.

Numbers never come from the AI: floors, units and simulations are built by
rule in `floors.py` / `spec.py` so every project stays valid for KARR AI.
"""

from __future__ import annotations

import base64
import json

from .assets import Asset

STORY_FIELDS = {
    "project_name": "Invented project name (2-4 words).",
    "client": "Invented developer / client company.",
    "architect": "Invented architecture practice.",
    "lead_consultant": "Invented engineering consultant.",
    "location": "Exactly one of: Dubai, Abu Dhabi, Sharjah & N.E.",
    "address": "Invented plot address in a real district of that emirate.",
    "author": "Invented person, initial + surname.",
    "approved_by": "Another invented person, initial + surname.",
    "operator_brand": "Invented hotel operator brand (one word).",
    "vision": "Design intent / vision paragraph, 90-130 words.",
    "site": "Site and context paragraph, 60-90 words.",
    "massing": "Massing, planning and core arrangement paragraph, 60-90 words.",
    "facade": "Facade and materials paragraph, 40-70 words.",
    "amenities": "Amenities paragraph, 40-70 words.",
    "sustainability": "Sustainability paragraph, 40-70 words.",
    "render_prompt": "One-sentence prompt for a photorealistic exterior render of this building.",
}

_SYSTEM = (
    "You write fictional architect design-report content for software testing. "
    "Every name of a project, company, person and brand must be invented and must not "
    "belong to a real company, developer, hotel brand, architect or person. "
    "Write plain, professional British English. Do not state unit counts, floor counts, "
    "lift numbers or areas: those come from the schedule. Return JSON only."
)


def _schema() -> dict:
    return {
        "name": "project_story",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": list(STORY_FIELDS),
            "properties": {k: {"type": "string", "description": v} for k, v in STORY_FIELDS.items()},
        },
    }


def generate_story(client, text_model: str, asset: Asset, model: str, opts: dict,
                   floors_summary: str, hint: str = "") -> dict:
    """Ask the text model for a project story. Raises on API or parse errors."""
    user = (
        f"Building type: {asset.classification} (DBC {model[-2:]}).\n"
        f"Building summary: {floors_summary}\n"
        f"Options: {json.dumps(opts)}\n"
        "If the options give a project_name or location, use them exactly.\n"
        f"Extra direction from the tester: {hint or 'none'}\n"
        "Write the story for this fictional project."
    )
    resp = client.chat.completions.create(
        model=text_model,
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": _schema()},
    )
    story = json.loads(resp.choices[0].message.content)
    story["source"] = text_model
    return story


# Tried in order after the configured model (gpt-image-1 was retired in Oct 2026).
IMAGE_MODEL_FALLBACKS = ["gpt-image-2.6-flare", "gpt-image-2.5-flare", "gpt-image-2"]


def generate_render(client, image_model: str, prompt: str) -> bytes:
    """Return PNG bytes of an exterior render. Raises the last API error if every model fails."""
    import openai

    full_prompt = prompt + ". Fictional building, no text, no logos, no watermark."
    last: Exception | None = None
    for model in dict.fromkeys([image_model, *IMAGE_MODEL_FALLBACKS]):
        try:
            resp = client.images.generate(model=model, prompt=full_prompt, size="1536x1024", n=1)
            return base64.b64decode(resp.data[0].b64_json)
        except (openai.NotFoundError, openai.BadRequestError) as e:
            last = e
    raise last  # type: ignore[misc]
