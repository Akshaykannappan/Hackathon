"""Centralized prompt templates and builder functions for Mesh API calls."""

from typing import Any

QUERY_PLANNER_SYSTEM_PROMPT = """You are a search query planner for a course recommendation system.
Analyze the user's positive interest topics and recent behavioural signals to generate 2 to 3 targeted semantic search queries.

CRITICAL INSTRUCTIONS:
1. Output ONLY a valid JSON object in the exact format:
   {"queries": ["query 1", "query 2", "query 3"]}
2. Do NOT include markdown code fences (no ```json ... ```), preamble, or extra text.
3. Focus ONLY on topics with positive interest scores and recent active user behaviour.
4. EXPLICITLY IGNORE any topics with negative interest scores or topics the user dislikes.
5. Make queries concise, distinct, and focused on specific course skills or domains."""

QUERY_PLANNER_USER_TEMPLATE = """User Interest Profile (Positive Signals Only):
{positive_interests}

Recent Behavioural Signals (3-5 actions):
{recent_signals}

Generate 2 to 3 targeted semantic search queries matching the user's top positive interests."""

GENERATOR_SYSTEM_PROMPT = """You are a persuasive learning advisor generating catalog-grounded course recommendations.
You will be provided with a qualitative profile of the learner's interests, their recent actions, and a numbered list of candidate courses.

CRITICAL HARD RULES:
1. Output ONLY a valid JSON object in the exact format:
   {{
     "message": "3-4 sentences of persuasive copy...",
     "products": [12, 45, 67],
     "reasoning": "1 sentence explaining why these courses fit the user's specific actions."
   }}
2. Do NOT include markdown code fences (no ```json ... ```), preamble, or extra text.
3. PRODUCT SELECTION HARD RULE: You MUST select product IDs ONLY from the provided candidate list. You are strictly forbidden from inventing, hallucinating, or referencing product IDs outside the candidate list.
4. The "message" MUST be 3 to 4 sentences of highly persuasive, natural copy referencing specific actions the learner took (e.g. searching for a topic, viewing a course).
5. Select 2 to 3 candidate products that best match the learner's intent."""

GENERATOR_USER_TEMPLATE = """Qualitative Interest Profile:
{qualitative_profile}

Recent Behavioural Signals:
{recent_signals}

Available Candidate Courses:
{candidate_list}

Recommend 2 to 3 courses from the candidate list above. Return ONLY the requested JSON object."""


def build_query_planner_prompt(
    profile: dict[str, float],
    recent_signals: list[str],
) -> list[dict[str, str]]:
    """Build system and user messages for the query planner LLM call."""
    positive_interests = {k: v for k, v in profile.items() if v > 0}

    profile_lines = []
    if positive_interests:
        for topic, score in sorted(positive_interests.items(), key=lambda x: x[1], reverse=True):
            profile_lines.append(f"- {topic}: {score:.2f}")
    else:
        profile_lines.append("- No positive interest signals recorded yet.")

    signals_lines = []
    if recent_signals:
        for sig in recent_signals[:5]:
            signals_lines.append(f"- {sig}")
    else:
        signals_lines.append("- General browsing activity.")

    user_content = QUERY_PLANNER_USER_TEMPLATE.format(
        positive_interests="\n".join(profile_lines),
        recent_signals="\n".join(signals_lines),
    )

    return [
        {"role": "system", "content": QUERY_PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _qualitative_interest_description(profile: dict[str, float]) -> str:
    """Format interest profile scores qualitatively rather than as raw numbers."""
    if not profile:
        return "No explicit interest history."

    strong = []
    medium = []
    emerging = []
    disliked = []

    for topic, score in sorted(profile.items(), key=lambda x: x[1], reverse=True):
        if score >= 0.6:
            strong.append(topic)
        elif score >= 0.3:
            medium.append(topic)
        elif score > 0.0:
            emerging.append(topic)
        else:
            disliked.append(topic)

    parts = []
    if strong:
        parts.append(f"Strong interests: {', '.join(strong)}")
    if medium:
        parts.append(f"Medium interests: {', '.join(medium)}")
    if emerging:
        parts.append(f"Emerging interests: {', '.join(emerging)}")
    if disliked:
        parts.append(f"Low interest / Avoid: {', '.join(disliked)}")

    return "\n".join(parts)


def build_generator_prompt(
    profile: dict[str, float],
    recent_signals: list[str],
    candidates: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build system and user messages for the recommendation generator LLM call."""
    qualitative_profile = _qualitative_interest_description(profile)

    signals_lines = []
    if recent_signals:
        for sig in recent_signals[:5]:
            signals_lines.append(f"- {sig}")
    else:
        signals_lines.append("- General catalog exploration")

    candidate_lines = []
    for idx, c in enumerate(candidates, start=1):
        c_id = c.get("id")
        title = c.get("title", "Untitled")
        desc = c.get("description", "")
        cat = c.get("category", "General")
        level = c.get("level", "all")
        candidate_lines.append(
            f"{idx}. [ID: {c_id}] \"{title}\" ({cat}, {level})\n   Description: {desc}"
        )

    user_content = GENERATOR_USER_TEMPLATE.format(
        qualitative_profile=qualitative_profile,
        recent_signals="\n".join(signals_lines),
        candidate_list="\n\n".join(candidate_lines),
    )

    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
