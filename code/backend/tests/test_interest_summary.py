"""Tests for the plain-English profile line shown on user-facing pages.

The hard rules: at most two categories, level topics as words, never a number,
and silence on an empty profile.
"""

from app.services.interest_summary import summarise_profile

CATEGORIES = ["Agentic AI", "Cybersecurity", "Data Engineering", "RAG"]


def test_empty_profile_says_nothing():
    assert summarise_profile({}, CATEGORIES) is None
    assert summarise_profile(None, CATEGORIES) is None


def test_all_negative_profile_says_nothing():
    """A profile of pure dislikes has nothing to volunteer."""
    assert summarise_profile({"rag": -0.4, "cybersecurity": -0.9}, CATEGORIES) is None


def test_one_category_with_a_level():
    line = summarise_profile(
        {"cybersecurity": 0.9, "level:advanced": 0.5}, CATEGORIES
    )
    assert line == "Based on your recent browsing — Cybersecurity, leaning advanced."


def test_two_categories_without_a_level():
    line = summarise_profile({"agentic_ai": 0.9, "rag": 0.6}, CATEGORIES)
    assert line == "You've been exploring Agentic AI and RAG."


def test_never_names_more_than_two_categories():
    line = summarise_profile(
        {"agentic_ai": 0.9, "rag": 0.8, "cybersecurity": 0.7, "data_engineering": 0.6},
        CATEGORIES,
    )
    # The two strongest, and nothing else.
    assert line == "You've been exploring Agentic AI and RAG."
    assert "Cybersecurity" not in line
    assert "Data Engineering" not in line


def test_never_prints_a_number():
    line = summarise_profile(
        {"agentic_ai": 0.9134, "rag": 0.6, "level:intermediate": 0.5}, CATEGORIES
    )
    assert line is not None
    assert not any(char.isdigit() for char in line)


def test_level_prefix_never_leaks():
    line = summarise_profile({"rag": 0.7, "level:beginner": 0.5}, CATEGORIES)
    assert "level:" not in line
    assert line.endswith("leaning beginner.")


def test_level_alone_still_produces_a_line():
    """Search-only behaviour can score a level without ever naming a category."""
    line = summarise_profile({"level:advanced": 0.5}, CATEGORIES)
    assert line == "You've been leaning towards advanced courses."


def test_negative_categories_are_not_named():
    line = summarise_profile({"agentic_ai": 0.9, "cybersecurity": -0.8}, CATEGORIES)
    assert line == "You've been exploring Agentic AI."


def test_search_topics_that_are_not_categories_are_ignored():
    """`airflow` is a real profile key but not a catalog category — it stays out."""
    line = summarise_profile({"airflow": 0.95, "data_engineering": 0.6}, CATEGORIES)
    assert line == "You've been exploring Data Engineering."


def test_unknown_level_word_is_dropped_rather_than_guessed():
    line = summarise_profile({"rag": 0.7, "level:expert": 0.5}, CATEGORIES)
    assert line == "You've been exploring RAG."
