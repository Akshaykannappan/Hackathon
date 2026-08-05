"""One plain-English sentence describing what the profile currently believes.

The raw profile is developer data: slugged topic keys, `level:` prefixes and
float scores. That belongs on the Console, where the numbers are the point.
On user-facing pages it reads as a debug dump, so this module renders the same
profile as a single readable line instead.

Rules, deliberately narrow:

- at most two categories are named
- level topics become words (beginner / intermediate / advanced), never scores
- no number is ever printed
- an empty or all-negative profile produces nothing at all, and the caller
  renders no line rather than an empty one

This is presentation only. It reads the profile and changes nothing about how
the profile is computed.
"""

from app.services.behavior_engine import LEVEL_PREFIX, slugify

MAX_NAMED_CATEGORIES = 2

# The only level words the copy will use. A level topic outside this set is
# dropped rather than guessed at.
KNOWN_LEVELS = ("beginner", "intermediate", "advanced")


def _join(names: list[str]) -> str:
    """"A" / "A and B" — the list never grows past two, so this is the whole case."""
    if len(names) == 1:
        return names[0]
    return f"{names[0]} and {names[1]}"


def summarise_profile(
    profile: dict[str, float] | None,
    categories: list[str],
) -> str | None:
    """Describe a profile in one sentence, or return None when there is nothing to say.

    `categories` are the catalog's real category names. Matching topic keys back
    against them is what lets the line print "Agentic AI" rather than the
    `agentic_ai` slug the profile actually stores.
    """
    if not profile:
        return None

    display_names = {slugify(name): name for name in categories}

    ranked_categories = sorted(
        (
            (display_names[topic], score)
            for topic, score in profile.items()
            if score > 0 and topic in display_names
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    named = [name for name, _ in ranked_categories[:MAX_NAMED_CATEGORIES]]

    ranked_levels = sorted(
        (
            (topic[len(LEVEL_PREFIX):], score)
            for topic, score in profile.items()
            if topic.startswith(LEVEL_PREFIX) and score > 0
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    level = next(
        (name for name, _ in ranked_levels if name in KNOWN_LEVELS),
        None,
    )

    if named and level:
        return f"Based on your recent browsing — {_join(named)}, leaning {level}."
    if named:
        return f"You've been exploring {_join(named)}."
    if level:
        return f"You've been leaning towards {level} courses."
    return None
