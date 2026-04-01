"""Tests for PAGAL OS knowledge graph module."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import knowledge as knowledge_module


@pytest.fixture(autouse=True)
def isolate_knowledge_db(tmp_path: Path):
    """Redirect the knowledge DB to a temp directory for each test."""
    test_db = tmp_path / "test_pagal.db"
    with patch.object(knowledge_module, "_DB_PATH", test_db):
        knowledge_module.init_db()
        yield


class TestAddAndSearch:
    """Test adding and searching knowledge nodes."""

    def test_add_and_search_knowledge(self) -> None:
        """Should add a fact and find it via search."""
        node_id = knowledge_module.add_knowledge(
            agent_name="learner",
            topic="Python",
            content="Python is a dynamically typed language",
            source="docs",
        )
        assert node_id > 0

        results = knowledge_module.search_knowledge("dynamically typed")
        assert len(results) >= 1
        assert any("dynamically typed" in r["content"] for r in results)

    def test_search_by_topic(self) -> None:
        """Should match on topic as well as content."""
        knowledge_module.add_knowledge("agent", "machine learning", "Uses neural networks", "")
        results = knowledge_module.search_knowledge("machine learning")
        assert len(results) >= 1

    def test_search_filtered_by_agent(self) -> None:
        """Should filter search results by agent name."""
        knowledge_module.add_knowledge("agent_a", "topic", "fact A", "")
        knowledge_module.add_knowledge("agent_b", "topic", "fact B", "")

        results = knowledge_module.search_knowledge("fact", agent_name="agent_a")
        assert all(r["agent_name"] == "agent_a" for r in results)

    def test_search_no_results(self) -> None:
        """Should return empty list when nothing matches."""
        results = knowledge_module.search_knowledge("xyznonexistent")
        assert results == []


class TestLinkKnowledge:
    """Test linking knowledge nodes."""

    def test_link_knowledge(self) -> None:
        """Should create an edge between two nodes."""
        id1 = knowledge_module.add_knowledge("agent", "Python", "Python lang", "")
        id2 = knowledge_module.add_knowledge("agent", "ML", "Machine Learning", "")

        success = knowledge_module.link_knowledge(id1, id2, "used_in")
        assert success is True

    def test_link_knowledge_with_default_relation(self) -> None:
        """Should use 'related_to' as default relation."""
        id1 = knowledge_module.add_knowledge("agent", "A", "fact A", "")
        id2 = knowledge_module.add_knowledge("agent", "B", "fact B", "")

        success = knowledge_module.link_knowledge(id1, id2)
        assert success is True


class TestGetRelated:
    """Test graph traversal to find related nodes."""

    def test_get_related(self) -> None:
        """Should find nodes connected by edges."""
        id1 = knowledge_module.add_knowledge("agent", "Python", "Language", "")
        id2 = knowledge_module.add_knowledge("agent", "Django", "Web framework", "")
        id3 = knowledge_module.add_knowledge("agent", "Flask", "Micro framework", "")

        knowledge_module.link_knowledge(id1, id2, "has_framework")
        knowledge_module.link_knowledge(id1, id3, "has_framework")

        related = knowledge_module.get_related(id1, depth=1)
        related_ids = {r["id"] for r in related}
        assert id2 in related_ids
        assert id3 in related_ids

    def test_get_related_no_connections(self) -> None:
        """Should return empty list for an isolated node."""
        node_id = knowledge_module.add_knowledge("agent", "Lonely", "No friends", "")
        related = knowledge_module.get_related(node_id, depth=2)
        assert related == []

    def test_get_related_depth(self) -> None:
        """Should traverse multiple hops with higher depth."""
        id1 = knowledge_module.add_knowledge("agent", "A", "Node A", "")
        id2 = knowledge_module.add_knowledge("agent", "B", "Node B", "")
        id3 = knowledge_module.add_knowledge("agent", "C", "Node C", "")

        knowledge_module.link_knowledge(id1, id2)
        knowledge_module.link_knowledge(id2, id3)

        # Depth 1 should only find B
        related_1 = knowledge_module.get_related(id1, depth=1)
        related_1_ids = {r["id"] for r in related_1}
        assert id2 in related_1_ids

        # Depth 2 should find B and C
        related_2 = knowledge_module.get_related(id1, depth=2)
        related_2_ids = {r["id"] for r in related_2}
        assert id2 in related_2_ids
        assert id3 in related_2_ids
