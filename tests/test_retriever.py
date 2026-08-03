"""Tests for the PawPal AI knowledge retriever."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_ai.retriever import KnowledgeRetriever

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge_base"


def make_retriever(**kwargs):
    return KnowledgeRetriever(KNOWLEDGE_DIR, **kwargs)


def test_index_builds_sections_from_all_files():
    retriever = make_retriever()
    files = {chunk.source_file for chunk in retriever.chunks}
    assert files == {
        "pet_profiles.md",
        "owner_preferences.md",
        "scheduling_rules.md",
        "task_templates.md",
    }
    # Section splitting: pet_profiles has one chunk per pet.
    pet_sections = [c for c in retriever.chunks if c.source_file == "pet_profiles.md"]
    assert {c.section for c in pet_sections} == {"Biscuit", "Mochi"}


def test_source_ids_are_stable_and_unique():
    retriever = make_retriever()
    ids = [chunk.source_id for chunk in retriever.chunks]
    assert len(ids) == len(set(ids))  # no duplicates
    assert "pet_profiles.md#biscuit" in ids
    assert "owner_preferences.md#default-owner" in ids
    assert "scheduling_rules.md#conflicts" in ids
    assert "task_templates.md#walk" in ids
    # Rebuilding the index yields the same IDs (stability).
    assert ids == [chunk.source_id for chunk in make_retriever().chunks]


def test_biscuit_query_retrieves_biscuit_profile():
    retriever = make_retriever()
    chunks = retriever.retrieve("Biscuit needs a 30-minute walk every morning")
    ids = [chunk.source_id for chunk in chunks]
    assert "pet_profiles.md#biscuit" in ids
    assert all(chunk.score > 0 for chunk in chunks)


def test_conflict_query_retrieves_scheduling_rules():
    retriever = make_retriever()
    chunks = retriever.retrieve("what happens when two tasks overlap and conflict")
    assert "scheduling_rules.md#conflicts" in [chunk.source_id for chunk in chunks]


def test_empty_query_returns_nothing():
    retriever = make_retriever()
    assert retriever.retrieve("") == []
    assert retriever.retrieve("   ") == []


def test_missing_directory_is_handled_gracefully():
    retriever = KnowledgeRetriever(Path("/nonexistent/knowledge_dir"))
    assert retriever.chunks == []
    assert retriever.retrieve("walk Biscuit") == []


def test_top_k_limits_results():
    retriever = make_retriever(top_k=2)
    chunks = retriever.retrieve("feed the dog and the cat every day walk litter")
    assert len(chunks) <= 2


def test_no_duplicate_chunks_in_results():
    retriever = make_retriever(top_k=10)
    chunks = retriever.retrieve("Biscuit walk feeding morning evening litter")
    ids = [chunk.source_id for chunk in chunks]
    assert len(ids) == len(set(ids))


def test_results_are_sorted_by_score():
    retriever = make_retriever(top_k=10)
    chunks = retriever.retrieve("Biscuit morning walk")
    scores = [chunk.score for chunk in chunks]
    assert scores == sorted(scores, reverse=True)


def test_source_file_filter():
    retriever = make_retriever(top_k=10)
    chunks = retriever.retrieve("walk Biscuit", source_files=["task_templates.md"])
    assert chunks and all(c.source_file == "task_templates.md" for c in chunks)


def test_known_source_ids():
    retriever = make_retriever()
    known = retriever.known_source_ids()
    assert "pet_profiles.md#mochi" in known
    assert "not_a_file.md#nope" not in known
