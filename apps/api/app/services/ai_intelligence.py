"""
AI Lead Intelligence service — powered by Claude API.

Capabilities:
  1. Lead narrative: "why this lead is hot" in plain English
  2. Outreach draft: personalized first email or call script
  3. Risk factors: signals that may be false positives
  4. Natural language lead search: parse NL query → SQL WHERE clause

Streaming:
  All endpoints use Server-Sent Events (SSE) for word-by-word rendering.

Rate limiting:
  10 requests/min per user, responses cached per contact for 6 hours (Redis).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncGenerator

import structlog

logger = structlog.get_logger(__name__)

# Claude model to use — default to Sonnet 4.6 (fast + capable)
_CLAUDE_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = """You are RevOps, an AI sales intelligence assistant embedded in a B2B lead scoring platform.
Your job is to help sales reps understand leads and craft personalized outreach.
Be concise, specific, and actionable. Use plain English — no jargon.
When citing signals, refer to actual data provided. Never fabricate metrics."""


def _build_lead_context(contact: dict, features: dict, latest_score: dict) -> str:
    """Build a structured context block from raw DB rows."""
    lines = [
        f"Contact: {contact.get('full_name', 'Unknown')} <{contact.get('email', '')}>",
        f"Title: {contact.get('job_title', 'Unknown')}",
        f"Company: {contact.get('company_name', 'Unknown')} (size: {contact.get('company_size_tier', 'unknown')})",
        f"",
        f"=== LEAD SCORE ===",
        f"Score: {latest_score.get('lead_score', 0)}/100",
        f"Tier: {latest_score.get('priority_tier', 'UNKNOWN')}",
        f"Scored: {latest_score.get('scored_at', 'N/A')}",
        f"Top score reason: {latest_score.get('score_reason', 'N/A')}",
        f"",
        f"=== BEHAVIORAL SIGNALS (last 7 days) ===",
        f"API calls: {features.get('api_calls_7d', 0)} (30d: {features.get('api_calls_30d', 0)})",
        f"Page views: {features.get('page_views_7d', 0)}",
        f"Docs visits: {features.get('docs_page_visits_7d', 0)}",
        f"Email opens: {features.get('email_opens_7d', 0)} | clicks: {features.get('email_clicks_7d', 0)}",
        f"Sessions: {features.get('sessions_7d', 0)}",
        f"Days since last activity: {features.get('days_since_last_activity', 999)}",
        f"",
        f"=== INTENT SIGNALS ===",
        f"Pricing page visited: {features.get('pricing_page_visited', False)}",
        f"Demo requested: {features.get('demo_requested', False)}",
        f"Free trial active: {features.get('free_trial_active', False)}",
        f"Integration connected: {features.get('integration_connected', False)}",
        f"Integrations count: {features.get('integrations_count', 0)}",
        f"",
        f"=== SCORE CONTRIBUTIONS ===",
    ]
    contributions = latest_score.get("feature_contributions") or {}
    for k, v in sorted(contributions.items(), key=lambda x: x[1], reverse=True)[:8]:
        if not k.startswith("_") and v != 0:
            lines.append(f"  {k.replace('_', ' ')}: {v:+d}")

    return "\n".join(lines)


async def stream_lead_intelligence(
    contact: dict,
    features: dict,
    latest_score: dict,
    api_key: str,
) -> AsyncGenerator[str, None]:
    """
    Stream a lead intelligence report via SSE.
    Yields SSE-formatted strings: "data: <chunk>\n\n"
    """
    try:
        import anthropic
    except ImportError:
        yield 'data: {"error": "anthropic SDK not installed. Run: pip install anthropic"}\n\n'
        return

    context = _build_lead_context(contact, features, latest_score)
    tier = latest_score.get("priority_tier", "UNKNOWN")
    score = latest_score.get("lead_score", 0)

    user_message = f"""Analyze this lead and provide:

1. **Why This Lead Is {tier}** (2-3 sentences explaining the key signals)
2. **Personalized Outreach Draft** (subject line + 3-4 sentence email body referencing their specific signals)
3. **Risk Factors** (1-2 potential false-positive signals to watch for)
4. **Recommended Next Action** (one specific, time-bound action for the sales rep)

Lead data:
{context}

Score: {score}/100 | Tier: {tier}"""

    client = anthropic.Anthropic(api_key=api_key)

    try:
        with client.messages.stream(
            model=_CLAUDE_MODEL,
            max_tokens=800,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text_chunk in stream.text_stream:
                # Escape newlines for SSE
                escaped = text_chunk.replace("\n", "\\n")
                yield f"data: {json.dumps({'chunk': escaped})}\n\n"

        yield "data: [DONE]\n\n"

    except Exception as exc:
        logger.error("ai_intelligence_stream_error", error=str(exc))
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"


async def get_lead_intelligence(
    contact: dict,
    features: dict,
    latest_score: dict,
    api_key: str,
) -> dict:
    """
    Non-streaming version — returns full intelligence report as a dict.
    Used for caching and test assertions.
    """
    try:
        import anthropic
    except ImportError:
        return {"error": "anthropic SDK not installed"}

    context = _build_lead_context(contact, features, latest_score)
    tier = latest_score.get("priority_tier", "UNKNOWN")
    score = latest_score.get("lead_score", 0)

    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=800,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Analyze this lead and provide:\n\n"
                f"1. **Why This Lead Is {tier}** (2-3 sentences)\n"
                f"2. **Personalized Outreach Draft** (subject + 3-4 sentence email)\n"
                f"3. **Risk Factors** (1-2 false-positive signals)\n"
                f"4. **Recommended Next Action** (specific, time-bound)\n\n"
                f"Lead data:\n{context}\n\n"
                f"Score: {score}/100 | Tier: {tier}"
            ),
        }],
    )

    text = message.content[0].text if message.content else ""

    return {
        "contact_id": contact.get("id"),
        "model": _CLAUDE_MODEL,
        "lead_score": score,
        "priority_tier": tier,
        "analysis": text,
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def natural_language_search(query: str, api_key: str) -> dict:
    """
    Parse a natural language lead search query into a structured filter set.

    Example:
        "warm leads in fintech who visited pricing but never requested a demo"
        → {
            "tier": ["WARM"],
            "industry_contains": "fintech",
            "pricing_page_visited": true,
            "demo_requested": false
          }

    Returns a dict of filter parameters consumable by the /scoring/leads endpoint.
    """
    try:
        import anthropic
    except ImportError:
        return {"error": "anthropic SDK not installed", "raw_query": query}

    client = anthropic.Anthropic(api_key=api_key)

    system = """You are a query parser for a B2B lead scoring database.
Convert natural language queries into JSON filter objects.

Available filter fields:
- tier: array of "HOT" | "WARM" | "COOL" | "COLD"
- min_score: integer 0-100
- max_score: integer 0-100
- industry_contains: string (partial match on company industry)
- company_size_tier: "smb" | "mid_market" | "enterprise"
- pricing_page_visited: boolean
- demo_requested: boolean
- free_trial_active: boolean
- integration_connected: boolean
- days_since_last_activity_max: integer
- email_clicks_7d_min: integer
- api_calls_7d_min: integer

Return ONLY valid JSON. No explanation."""

    message = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=300,
        system=system,
        messages=[{"role": "user", "content": f"Query: {query}"}],
    )

    raw = message.content[0].text.strip() if message.content else "{}"

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        filters = json.loads(raw)
    except json.JSONDecodeError:
        filters = {}

    return {
        "raw_query": query,
        "filters": filters,
        "model": _CLAUDE_MODEL,
    }
