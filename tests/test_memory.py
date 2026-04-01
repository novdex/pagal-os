"""Tests for PAGAL OS cross-session memory module."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import memory as mem_module


@pytest.fixture(autouse=True)
def isolate_memory_db(tmp_path: Path):
    """Redirect the memory DB to a temp directory for each test."""
    test_db = tmp_path / "test_pagal.db"
    with patch.object(mem_module, "_DB_PATH", test_db):
        mem_module.init_memory_db()
        yield


class TestSaveAndRetrieveMessages:
    """Test persisting and loading messages."""

    def test_save_and_retrieve_messages(self) -> None:
        """Should save a message and retrieve it by agent name."""
        mem_module.save_message("agent_a", "sess1", "user", "Hello there")
        msgs = mem_module.get_recent_messages("agent_a", limit=10)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello there"

    def test_multiple_messages_ordered(self) -> None:
        """Messages should be returned in chronological order (oldest first)."""
        mem_module.save_message("agent_a", "s1", "user", "first")
        mem_module.save_message("agent_a", "s1", "assistant", "second")
        mem_module.save_message("agent_a", "s1", "user", "third")
        msgs = mem_module.get_recent_messages("agent_a", limit=10)
        assert len(msgs) == 3
        assert msgs[0]["content"] == "first"
        assert msgs[1]["content"] == "second"
        assert msgs[2]["content"] == "third"

    def test_separate_agents_isolated(self) -> None:
        """Messages from different agents should be isolated."""
        mem_module.save_message("agent_a", "s1", "user", "for A")
        mem_module.save_message("agent_b", "s1", "user", "for B")
        msgs_a = mem_module.get_recent_messages("agent_a")
        msgs_b = mem_module.get_recent_messages("agent_b")
        assert len(msgs_a) == 1
        assert len(msgs_b) == 1
        assert msgs_a[0]["content"] == "for A"


class TestMemoryContext:
    """Test the get_memory_context function that builds prompt context."""

    def test_memory_context_includes_old_sessions(self) -> None:
        """Context should include messages from previous sessions."""
        mem_module.save_message("ctx_agent", "session_old", "user", "old message")
        mem_module.save_message("ctx_agent", "session_new", "user", "new message")

        context = mem_module.get_memory_context("ctx_agent")
        assert "old message" in context
        assert "new message" in context
        assert "MEMORY FROM PAST CONVERSATIONS" in context

    def test_empty_memory_returns_empty_string(self) -> None:
        """Should return empty string when no memory exists."""
        context = mem_module.get_memory_context("nonexistent_agent")
        assert context == ""


class TestSummarizeOldMessages:
    """Test the summarization of old messages."""

    def test_summarize_old_messages(self) -> None:
        """Should summarize older messages and keep recent ones."""
        # Insert 25 messages (keep_recent=20 means 5 get summarized)
        for i in range(25):
            mem_module.save_message("sum_agent", "s1", "user", f"Message number {i}")

        summarized = mem_module.summarize_old_messages("sum_agent", keep_recent=20)
        assert summarized == 5

        # Should now have 20 messages
        remaining = mem_module.get_recent_messages("sum_agent", limit=100)
        assert len(remaining) == 20

    def test_summarize_not_enough_messages(self) -> None:
        """Should return 0 when there are fewer messages than keep_recent."""
        mem_module.save_message("sum_agent2", "s1", "user", "only one")
        result = mem_module.summarize_old_messages("sum_agent2", keep_recent=20)
        assert result == 0


class TestSearchMemory:
    """Test keyword search across memory."""

    def test_search_memory(self) -> None:
        """Should find messages matching the search query."""
        mem_module.save_message("search_agent", "s1", "user", "Python is great")
        mem_module.save_message("search_agent", "s1", "user", "I love JavaScript")
        mem_module.save_message("search_agent", "s1", "user", "Python ML project")

        results = mem_module.search_memory("search_agent", "Python")
        assert len(results) >= 2
        for r in results:
            assert "Python" in r["content"]

    def test_search_no_results(self) -> None:
        """Should return empty list when no matches found."""
        mem_module.save_message("search_agent2", "s1", "user", "hello world")
        results = mem_module.search_memory("search_agent2", "xyznonexistent")
        assert results == []

    def test_search_includes_summaries(self) -> None:
        """Should search across both messages and summaries."""
        # Create enough messages to trigger summarization
        for i in range(25):
            mem_module.save_message("sum_search", "s1", "user", f"Unique keyword alpha {i}")

        mem_module.summarize_old_messages("sum_search", keep_recent=20)

        # Should find results in summaries too
        results = mem_module.search_memory("sum_search", "alpha")
        assert len(results) > 0
