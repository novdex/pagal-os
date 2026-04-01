"""Tests for PAGAL OS worlds and rooms module."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import worlds as worlds_module
from src.core.worlds import (
    Room,
    World,
    create_room,
    create_world,
    get_room_context,
    send_to_room,
)


@pytest.fixture(autouse=True)
def isolate_worlds(tmp_path: Path):
    """Redirect worlds storage and reset in-memory cache for each test."""
    test_file = tmp_path / "worlds.json"
    with patch.object(worlds_module, "_WORLDS_FILE", test_file):
        # Reset the in-memory cache
        worlds_module._worlds.clear()
        worlds_module._loaded = False
        yield


class TestCreateWorld:
    """Test world creation."""

    def test_create_world(self) -> None:
        """Should create a world with a unique ID."""
        world = create_world("test_agent", "my_world")
        assert isinstance(world, World)
        assert world.agent_name == "test_agent"
        assert world.name == "my_world"
        assert len(world.id) > 0
        assert world.created_at != ""

    def test_create_multiple_worlds(self) -> None:
        """Should allow creating multiple worlds for the same agent."""
        w1 = create_world("agent_a")
        w2 = create_world("agent_a")
        assert w1.id != w2.id


class TestCreateRoom:
    """Test room creation within a world."""

    def test_create_room(self) -> None:
        """Should create a room inside an existing world."""
        world = create_world("agent_a")
        room = create_room(world.id, "general")
        assert room is not None
        assert isinstance(room, Room)
        assert room.name == "general"
        assert room.world_id == world.id

    def test_create_room_invalid_world(self) -> None:
        """Should return None for a nonexistent world."""
        room = create_room("nonexistent_world_id", "test_room")
        assert room is None


class TestSendToRoom:
    """Test sending messages to rooms."""

    def test_send_to_room(self) -> None:
        """Should add a message to the room."""
        world = create_world("agent_a")
        room = create_room(world.id, "chat")
        assert room is not None

        success = send_to_room(world.id, room.id, "user", "Hello!")
        assert success is True

    def test_send_to_nonexistent_room(self) -> None:
        """Should return False for a nonexistent room."""
        world = create_world("agent_a")
        success = send_to_room(world.id, "fake_room_id", "user", "Hello?")
        assert success is False


class TestGetRoomContext:
    """Test retrieving room conversation context."""

    def test_get_room_context(self) -> None:
        """Should return all messages in a room in order."""
        world = create_world("agent_a")
        room = create_room(world.id, "context_test")
        assert room is not None

        send_to_room(world.id, room.id, "user", "First message")
        send_to_room(world.id, room.id, "assistant", "Second message")
        send_to_room(world.id, room.id, "user", "Third message")

        context = get_room_context(world.id, room.id)
        assert len(context) == 3
        assert context[0]["content"] == "First message"
        assert context[1]["role"] == "assistant"
        assert context[2]["content"] == "Third message"

    def test_get_room_context_empty(self) -> None:
        """Should return empty list for room with no messages."""
        world = create_world("agent_a")
        room = create_room(world.id, "empty_room")
        assert room is not None

        context = get_room_context(world.id, room.id)
        assert context == []

    def test_get_room_context_nonexistent(self) -> None:
        """Should return empty list for nonexistent room."""
        context = get_room_context("fake_world", "fake_room")
        assert context == []
