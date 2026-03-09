"""
AI-powered product recall detection using Claude (Anthropic).

Responsibilities:
  - Analyse marketplace listing text + images to determine if the listing
    matches a known recalled / banned product.
  - Return a confidence score (0-1), structured match data, and a human-
    readable explanation.

Uses two complementary strategies:
  1. Text analysis  – Claude reads the listing title / description and
     compares it against the recalled product's attributes (name, brand,
     model, keywords).
  2. Vision analysis – Claude examines listing images and reference recall
     images to visually confirm the product.
"""

import base64
import logging
from io import BytesIO
from typing import Any

import anthropic
import httpx
from PIL import Image

from ..config import get_settings
from ..models.recall import RecalledProduct

logger = logging.getLogger(__name__)
settings = get_settings()

# Global Anthropic client (initialised lazily so tests can patch it)
_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def detect_listing(
    listing_title: str,
    listing_description: str,
    listing_image_urls: list[str],
    recalled_product: RecalledProduct,
) -> dict[str, Any]:
    """
    Analyse a C2C marketplace listing against a recalled product record.

    Returns:
        {
            "is_match": bool,
            "confidence": float,          # 0.0 – 1.0
            "text_match_score": float,
            "image_match_score": float | None,
            "match_method": str,          # "text" | "image" | "combined" | "none"
            "reasoning": str,
            "matched_attributes": list[str],
        }
    """
    text_result = await _text_analysis(
        listing_title, listing_description, recalled_product
    )

    image_result = None
    if settings.IMAGE_ANALYSIS_ENABLED and listing_image_urls:
        image_result = await _image_analysis(
            listing_image_urls, recalled_product
        )

    return _combine_results(text_result, image_result)


# ---------------------------------------------------------------------------
# Text analysis
# ---------------------------------------------------------------------------

_TEXT_SYSTEM = """\
You are a product safety expert specialising in consumer product recalls and bans.
Your task is to determine whether a marketplace listing is selling a recalled or banned product.
Respond ONLY in valid JSON following the schema provided in the user message.
"""

_TEXT_PROMPT_TEMPLATE = """\
## Recalled Product Information
- Name: {product_name}
- Brand: {brand}
- Model Numbers: {models}
- Product Type: {product_type}
- Recall Number: {recall_number}
- Hazard: {hazard}
- Description: {recall_desc}
- Keywords: {keywords}

## Marketplace Listing
- Title: {title}
- Description: {description}

## Task
Determine whether the marketplace listing is selling the recalled/banned product above.
Consider partial matches, misspellings, and re-listings under different names.

Respond with a JSON object matching this exact schema:
{{
  "is_match": <boolean>,
  "confidence": <number 0.0-1.0>,
  "matched_attributes": <array of strings, e.g. ["brand", "model_number", "description"]>,
  "reasoning": <string, 1-3 sentences explaining your decision>
}}
"""


async def _text_analysis(
    title: str,
    description: str,
    recall: RecalledProduct,
) -> dict[str, Any]:
    prompt = _TEXT_PROMPT_TEMPLATE.format(
        product_name=recall.product_name,
        brand=recall.brand or "N/A",
        models=", ".join(recall.model_numbers or []) or "N/A",
        product_type=recall.product_type or "N/A",
        recall_number=recall.recall_number or "N/A",
        hazard=recall.hazard_description or "N/A",
        recall_desc=recall.product_description or "N/A",
        keywords=", ".join(recall.search_keywords or []) or "N/A",
        title=title or "(no title)",
        description=(description or "(no description)")[:2000],
    )

    try:
        client = get_client()
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=_TEXT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        import json
        result = json.loads(raw)
        return {
            "is_match": bool(result.get("is_match", False)),
            "confidence": float(result.get("confidence", 0.0)),
            "matched_attributes": result.get("matched_attributes", []),
            "reasoning": result.get("reasoning", ""),
            "error": None,
        }
    except Exception as exc:
        logger.error("Text analysis error: %s", exc)
        return {
            "is_match": False,
            "confidence": 0.0,
            "matched_attributes": [],
            "reasoning": "",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Vision analysis
# ---------------------------------------------------------------------------

_VISION_SYSTEM = """\
You are a product safety expert with expertise in visually identifying recalled and banned consumer products.
Respond ONLY in valid JSON following the schema provided in the user message.
"""

_VISION_PROMPT_TEMPLATE = """\
## Recalled Product
- Name: {product_name}
- Brand: {brand}
- Product Type: {product_type}
- Hazard: {hazard}

The first image(s) are from the marketplace listing.
The remaining image(s) (if any) are official CPSC recall reference images.

## Task
Visually determine whether the listing images show the recalled/banned product.
Look for matching shape, colour, branding, labels, and distinctive features.

Respond with a JSON object matching this exact schema:
{{
  "is_match": <boolean>,
  "confidence": <number 0.0-1.0>,
  "visual_features": <array of strings describing matched visual features>,
  "reasoning": <string, 1-3 sentences>
}}
"""

MAX_LISTING_IMAGES = 3
MAX_RECALL_IMAGES = 2
MAX_IMAGE_BYTES = 1_500_000   # ~1.5 MB per image after resize


async def _fetch_image_b64(url: str) -> tuple[str, str] | None:
    """Download an image and return (base64_data, media_type) or None."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                content_type = "image/jpeg"
            data = resp.content

            # Resize if too large
            if len(data) > MAX_IMAGE_BYTES:
                img = Image.open(BytesIO(data))
                img.thumbnail((800, 800))
                buf = BytesIO()
                img.save(buf, format="JPEG")
                data = buf.getvalue()
                content_type = "image/jpeg"

            return base64.standard_b64encode(data).decode(), content_type
    except Exception as exc:
        logger.debug("Could not fetch image %s: %s", url, exc)
        return None


async def _image_analysis(
    listing_image_urls: list[str],
    recall: RecalledProduct,
) -> dict[str, Any] | None:
    content_blocks: list[dict] = []

    # Listing images
    for url in listing_image_urls[:MAX_LISTING_IMAGES]:
        fetched = await _fetch_image_b64(url)
        if fetched:
            b64, mt = fetched
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mt, "data": b64},
            })

    if not content_blocks:
        return None  # No usable images

    # Recall reference images
    for url in (recall.image_urls or [])[:MAX_RECALL_IMAGES]:
        fetched = await _fetch_image_b64(url)
        if fetched:
            b64, mt = fetched
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mt, "data": b64},
            })

    # Add the text prompt at the end
    content_blocks.append({
        "type": "text",
        "text": _VISION_PROMPT_TEMPLATE.format(
            product_name=recall.product_name,
            brand=recall.brand or "N/A",
            product_type=recall.product_type or "N/A",
            hazard=recall.hazard_description or "N/A",
        ),
    })

    try:
        client = get_client()
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=_VISION_SYSTEM,
            messages=[{"role": "user", "content": content_blocks}],
        )
        raw = message.content[0].text.strip()
        import json
        result = json.loads(raw)
        return {
            "is_match": bool(result.get("is_match", False)),
            "confidence": float(result.get("confidence", 0.0)),
            "visual_features": result.get("visual_features", []),
            "reasoning": result.get("reasoning", ""),
            "error": None,
        }
    except Exception as exc:
        logger.error("Vision analysis error: %s", exc)
        return {
            "is_match": False,
            "confidence": 0.0,
            "visual_features": [],
            "reasoning": "",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Result combination
# ---------------------------------------------------------------------------

def _combine_results(
    text: dict[str, Any],
    image: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge text and vision results into a single detection result."""
    text_conf = text.get("confidence", 0.0)
    text_match = text.get("is_match", False)

    if image is None:
        final_conf = text_conf
        final_match = text_match
        method = "text"
        reasoning = text.get("reasoning", "")
        image_score = None
    else:
        img_conf = image.get("confidence", 0.0)
        img_match = image.get("is_match", False)
        # Weighted average: text 40%, image 60% (visual is stronger signal)
        final_conf = 0.4 * text_conf + 0.6 * img_conf
        final_match = text_match or img_match
        method = "combined"
        reasoning = (
            f"Text analysis: {text.get('reasoning', '')} "
            f"Image analysis: {image.get('reasoning', '')}"
        ).strip()
        image_score = img_conf

    return {
        "is_match": final_match and final_conf >= settings.AI_CONFIDENCE_THRESHOLD,
        "confidence": round(final_conf, 4),
        "text_match_score": round(text_conf, 4),
        "image_match_score": round(image_score, 4) if image_score is not None else None,
        "match_method": method,
        "reasoning": reasoning,
        "matched_attributes": text.get("matched_attributes", []),
    }


# ---------------------------------------------------------------------------
# Batch scanning helper
# ---------------------------------------------------------------------------

async def batch_detect(
    listings: list[dict[str, Any]],
    recall: RecalledProduct,
) -> list[dict[str, Any]]:
    """
    Run detect_listing concurrently across multiple raw listing dicts.

    Each listing dict should have keys:
        title, description, image_urls
    """
    import asyncio
    tasks = [
        detect_listing(
            listing_title=lst.get("title", ""),
            listing_description=lst.get("description", ""),
            listing_image_urls=lst.get("image_urls", []),
            recalled_product=recall,
        )
        for lst in listings
    ]
    return await asyncio.gather(*tasks)
