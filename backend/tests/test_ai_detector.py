"""
Unit tests for the AI detector module.
Uses mocking to avoid real Anthropic API calls.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.app.services.ai_detector import (
    _text_analysis,
    _combine_results,
    detect_listing,
)
from backend.app.models.recall import RecalledProduct


def make_recall(**kwargs):
    r = RecalledProduct()
    r.id = 1
    r.product_name = kwargs.get("product_name", "Acme Widget X200")
    r.brand = kwargs.get("brand", "Acme Corp")
    r.model_numbers = kwargs.get("model_numbers", ["X200", "X200B"])
    r.product_type = kwargs.get("product_type", "Toy")
    r.recall_number = kwargs.get("recall_number", "23-001")
    r.hazard_description = kwargs.get("hazard_description", "Choking hazard")
    r.product_description = kwargs.get("product_description", "Small plastic widget")
    r.search_keywords = kwargs.get("search_keywords", ["acme", "widget", "x200"])
    r.image_urls = kwargs.get("image_urls", [])
    return r


# ── _combine_results ─────────────────────────────────────────────────────────

def test_combine_text_only_match():
    text = {"is_match": True, "confidence": 0.9, "matched_attributes": ["brand"], "reasoning": "Match"}
    result = _combine_results(text, None)
    assert result["is_match"] is True
    assert result["confidence"] == 0.9
    assert result["match_method"] == "text"
    assert result["image_match_score"] is None


def test_combine_text_only_no_match():
    text = {"is_match": False, "confidence": 0.3, "matched_attributes": [], "reasoning": "No match"}
    result = _combine_results(text, None)
    assert result["is_match"] is False


def test_combine_with_image():
    text  = {"is_match": True, "confidence": 0.8, "matched_attributes": ["brand"], "reasoning": "T"}
    image = {"is_match": True, "confidence": 0.9, "visual_features": ["logo"], "reasoning": "I"}
    result = _combine_results(text, image)
    assert result["match_method"] == "combined"
    # Weighted: 0.4*0.8 + 0.6*0.9 = 0.86
    assert abs(result["confidence"] - 0.86) < 0.01
    assert result["image_match_score"] == 0.9


def test_combine_below_threshold():
    """Even if both match=True, low confidence should not trigger is_match."""
    text  = {"is_match": True, "confidence": 0.4, "matched_attributes": [], "reasoning": ""}
    image = {"is_match": True, "confidence": 0.5, "visual_features": [], "reasoning": ""}
    result = _combine_results(text, image)
    # 0.4*0.4 + 0.6*0.5 = 0.46 < 0.75 threshold
    assert result["is_match"] is False


# ── _text_analysis ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_text_analysis_match():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "is_match": True,
        "confidence": 0.92,
        "matched_attributes": ["brand", "model_number"],
        "reasoning": "Brand and model match the recall record.",
    }))]

    recall = make_recall()

    with patch("backend.app.services.ai_detector.get_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_client_fn.return_value = mock_client

        result = await _text_analysis(
            title="Acme Widget X200 for sale",
            description="Selling my Acme X200 widget",
            recall=recall,
        )

    assert result["is_match"] is True
    assert result["confidence"] == 0.92
    assert "brand" in result["matched_attributes"]
    assert result["error"] is None


@pytest.mark.asyncio
async def test_text_analysis_no_match():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "is_match": False,
        "confidence": 0.1,
        "matched_attributes": [],
        "reasoning": "Unrelated product.",
    }))]

    recall = make_recall()

    with patch("backend.app.services.ai_detector.get_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_client_fn.return_value = mock_client

        result = await _text_analysis("iPhone for sale", "Like new iPhone", recall)

    assert result["is_match"] is False


@pytest.mark.asyncio
async def test_text_analysis_api_error():
    recall = make_recall()

    with patch("backend.app.services.ai_detector.get_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))
        mock_client_fn.return_value = mock_client

        result = await _text_analysis("title", "desc", recall)

    assert result["is_match"] is False
    assert result["confidence"] == 0.0
    assert result["error"] is not None


# ── detect_listing integration ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detect_listing_full():
    mock_text_response = MagicMock()
    mock_text_response.content = [MagicMock(text=json.dumps({
        "is_match": True, "confidence": 0.88,
        "matched_attributes": ["brand"], "reasoning": "Matches.",
    }))]

    recall = make_recall()

    with patch("backend.app.services.ai_detector.get_client") as mock_client_fn:
        with patch("backend.app.services.ai_detector.settings") as mock_settings:
            mock_settings.AI_CONFIDENCE_THRESHOLD = 0.75
            mock_settings.IMAGE_ANALYSIS_ENABLED = False  # skip image analysis
            mock_settings.ANTHROPIC_API_KEY = "test"

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_text_response)
            mock_client_fn.return_value = mock_client

            result = await detect_listing(
                listing_title="Acme Widget X200",
                listing_description="Brand new, still in box",
                listing_image_urls=[],
                recalled_product=recall,
            )

    assert result["is_match"] is True
    assert result["confidence"] >= 0.75
    assert result["match_method"] == "text"
