"""
Tests for Feature 5: AI Lead Intelligence service.

Covers:
  - _build_lead_context produces expected sections
  - natural_language_search returns structured filters
  - get_lead_intelligence handles missing API key gracefully
  - Streaming generator emits SSE-formatted chunks
"""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


SAMPLE_CONTACT = {
    "id": "contact-001",
    "email": "alice@acme.com",
    "full_name": "Alice Smith",
    "job_title": "Head of Engineering",
    "company_name": "Acme Corp",
    "company_size_tier": "mid_market",
}

SAMPLE_FEATURES = {
    "api_calls_7d": 25,
    "api_calls_30d": 80,
    "page_views_7d": 12,
    "pricing_page_visited": True,
    "email_opens_7d": 4,
    "email_clicks_7d": 2,
    "docs_page_visits_7d": 3,
    "demo_requested": True,
    "free_trial_active": False,
    "integration_connected": True,
    "integrations_count": 2,
    "sessions_7d": 5,
    "days_since_last_activity": 2,
}

SAMPLE_SCORE = {
    "lead_score": 88,
    "priority_tier": "HOT",
    "score_reason": "demo_requested (+20), api_calls_7d (+30)",
    "feature_contributions": {"demo_requested": 20, "api_calls_7d": 30},
    "scored_at": "2026-04-08T10:00:00+00:00",
}


class TestBuildLeadContext:
    def test_context_includes_score(self):
        from app.services.ai_intelligence import _build_lead_context
        ctx = _build_lead_context(SAMPLE_CONTACT, SAMPLE_FEATURES, SAMPLE_SCORE)
        assert "88" in ctx
        assert "HOT" in ctx

    def test_context_includes_contact_info(self):
        from app.services.ai_intelligence import _build_lead_context
        ctx = _build_lead_context(SAMPLE_CONTACT, SAMPLE_FEATURES, SAMPLE_SCORE)
        assert "Alice Smith" in ctx
        assert "alice@acme.com" in ctx
        assert "Head of Engineering" in ctx

    def test_context_includes_behavioral_signals(self):
        from app.services.ai_intelligence import _build_lead_context
        ctx = _build_lead_context(SAMPLE_CONTACT, SAMPLE_FEATURES, SAMPLE_SCORE)
        assert "25" in ctx  # api_calls_7d
        assert "Pricing page visited: True" in ctx

    def test_context_includes_intent_signals(self):
        from app.services.ai_intelligence import _build_lead_context
        ctx = _build_lead_context(SAMPLE_CONTACT, SAMPLE_FEATURES, SAMPLE_SCORE)
        assert "Demo requested: True" in ctx

    def test_context_handles_empty_features(self):
        from app.services.ai_intelligence import _build_lead_context
        ctx = _build_lead_context(SAMPLE_CONTACT, {}, {})
        assert "Alice Smith" in ctx  # contact info still present


class TestGetLeadIntelligenceMissingKey:
    @pytest.mark.asyncio
    async def test_missing_anthropic_sdk_returns_error(self):
        import app.services.ai_intelligence as ai_module
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("No module named 'anthropic'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            # Re-import to force the ImportError path inside the function
            result = await ai_module.get_lead_intelligence(
                SAMPLE_CONTACT, SAMPLE_FEATURES, SAMPLE_SCORE, api_key="fake-key"
            )
        assert "error" in result


class TestNaturalLanguageSearchFilters:
    @pytest.mark.asyncio
    async def test_returns_structured_filters(self):
        import anthropic as anthropic_module
        from app.services.ai_intelligence import natural_language_search

        mock_content = MagicMock()
        mock_content.text = '{"tier": ["HOT"], "pricing_page_visited": true}'

        mock_message = MagicMock()
        mock_message.content = [mock_content]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        with patch.object(anthropic_module, "Anthropic", return_value=mock_client):
            result = await natural_language_search(
                "HOT leads who visited pricing page",
                api_key="test-key",
            )

        assert "filters" in result
        assert result["filters"].get("tier") == ["HOT"]
        assert result["filters"].get("pricing_page_visited") is True

    @pytest.mark.asyncio
    async def test_malformed_json_returns_empty_filters(self):
        import anthropic as anthropic_module
        from app.services.ai_intelligence import natural_language_search

        mock_content = MagicMock()
        mock_content.text = "not valid json at all"

        mock_message = MagicMock()
        mock_message.content = [mock_content]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        with patch.object(anthropic_module, "Anthropic", return_value=mock_client):
            result = await natural_language_search("anything", api_key="test-key")

        assert result["filters"] == {}
        assert result["raw_query"] == "anything"


class TestStreamIntelligence:
    @pytest.mark.asyncio
    async def test_streaming_yields_sse_format(self):
        import anthropic as anthropic_module
        from app.services.ai_intelligence import stream_lead_intelligence

        def fake_text_stream():
            yield "Why this"
            yield " lead is HOT"

        mock_stream = MagicMock()
        mock_stream.text_stream = fake_text_stream()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()
        mock_client.messages.stream.return_value = mock_stream

        with patch.object(anthropic_module, "Anthropic", return_value=mock_client):
            chunks = []
            async for chunk in stream_lead_intelligence(
                SAMPLE_CONTACT, SAMPLE_FEATURES, SAMPLE_SCORE, api_key="test-key"
            ):
                chunks.append(chunk)

        data_chunks = [c for c in chunks if c != "data: [DONE]\n\n"]
        assert len(data_chunks) > 0
        for chunk in data_chunks:
            assert chunk.startswith("data: ")
            payload = json.loads(chunk[6:])
            assert "chunk" in payload

    @pytest.mark.asyncio
    async def test_streaming_ends_with_done(self):
        import anthropic as anthropic_module
        from app.services.ai_intelligence import stream_lead_intelligence

        def fake_text_stream():
            yield "test content"

        mock_stream = MagicMock()
        mock_stream.text_stream = fake_text_stream()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()
        mock_client.messages.stream.return_value = mock_stream

        with patch.object(anthropic_module, "Anthropic", return_value=mock_client):
            chunks = []
            async for c in stream_lead_intelligence(
                SAMPLE_CONTACT, SAMPLE_FEATURES, SAMPLE_SCORE, api_key="test-key"
            ):
                chunks.append(c)

        assert chunks[-1] == "data: [DONE]\n\n"
