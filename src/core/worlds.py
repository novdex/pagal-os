"""PAGAL OS Worlds & Rooms — context isolation for agents.

Each agent gets its own 'world' (workspace). Within a world, conversations
happen in 'rooms'. This provides clean context isolation: a Telegram chat is
one room, a CLI session is another room, both under the same agent's world.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Persistent storage file
_WORLDS_FILE: Path = Path.home() / ".pagal-os" / "worlds.json"

# In-memory cache of all worlds
_worlds: dict[str, "World"] = {}
_loaded: bool = False


@dataclass
class Room:
    """A conversation room within a world.

    Attributes:
        id: Unique room identifier.
        name: Human-readable room name (e.g. 'telegram-123', 'cli-session').
        world_id: The world this room belongs to.
        agent_name: The agent that owns this room's world.
        messages: List of message dicts with 'role', 'content', 'timestamp'.
        created_at: ISO timestamp of when the room was created.
    """

    id: str
    name: str
    world_id: str
    agent_name: str
    messages: list[dict[str, str]] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize room to a JSON-compatible dict."""
        return {
            "id": self.id,
            "name": self.name,
            "world_id": self.world_id,
            "agent_name": self.agent_name,
            "messages": self.messages[-200:],  # Keep last 200 messages per room
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Room":
        """Deserialize a Room from a dict.

        Args:
            data: Dict with room fields.

        Returns:
            A Room instance.
        """
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            world_id=data.get("world_id", ""),
            agent_name=data.get("agent_name", ""),
            messages=data.get("messages", []),
            created_at=data.get("created_at", ""),
        )


@dataclass
class World:
    """A workspace/world for an agent, containing multiple rooms.

    Attributes:
        id: Unique world identifier.
        name: Human-readable world name.
        agent_name: The agent this world belongs to.
        rooms: Dict mapping room_id to Room.
        created_at: ISO timestamp of creation.
    """

    id: str
    name: str
    agent_name: str
    rooms: dict[str, Room] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize world to a JSON-compatible dict."""
        return {
            "id": self.id,
            "name": self.name,
            "agent_name": self.agent_name,
            "rooms": {rid: room.to_dict() for rid, room in self.rooms.items()},
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "World":
        """Deserialize a World from a dict.

        Args:
            data: Dict with world fields.

        Returns:
            A World instance.
        """
        rooms_raw = data.get("rooms", {})
        rooms = {rid: Room.from_dict(rdata) for rid, rdata in rooms_raw.items()}
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            agent_name=data.get("agent_name", ""),
            rooms=rooms,
            created_at=data.get("created_at", ""),
        )


def _load_worlds() -> None:
    """Load worlds from disk into memory cache."""
    global _worlds, _loaded

    if _loaded:
        return

    try:
        if _WORLDS_FILE.exists():
            raw = json.loads(_WORLDS_FILE.read_text(encoding="utf-8"))
            for wid, wdata in raw.items():
                _worlds[wid] = World.from_dict(wdata)
            logger.debug("Loaded %d worlds from disk", len(_worlds))
    except Exception as e:
        logger.error("Failed to load worlds from %s: %s", _WORLDS_FILE, e)

    _loaded = True


def _save_worlds() -> None:
    """Persist all worlds to disk."""
    try:
        _WORLDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {wid: w.to_dict() for wid, w in _worlds.items()}
        _WORLDS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("Saved %d worlds to disk", len(_worlds))
    except Exception as e:
        logger.error("Failed to save worlds to %s: %s", _WORLDS_FILE, e)


def create_world(agent_name: str, name: str = "default") -> World:
    """Create a new world for an agent.

    Args:
        agent_name: The agent that owns this world.
        name: A human-readable name for the world.

    Returns:
        The newly created World.
    """
    _load_worlds()

    now = datetime.now(timezone.utc).isoformat()
    world = World(
        id=uuid.uuid4().hex[:12],
        name=name,
        agent_name=agent_name,
        rooms={},
        created_at=now,
    )
    _worlds[world.id] = world
    _save_worlds()

    logger.info("Created world '%s' for agent '%s'", world.id, agent_name)
    return world


def get_or_create_world(agent_name: str) -> World:
    """Get the existing world for an agent, or create a new one.

    Looks for a world where agent_name matches. If multiple exist, returns
    the most recently created one.

    Args:
        agent_name: The agent to find/create a world for.

    Returns:
        The agent's World.
    """
    _load_worlds()

    # Find existing world for this agent
    agent_worlds = [w for w in _worlds.values() if w.agent_name == agent_name]
    if agent_worlds:
        # Return the most recently created one
        return max(agent_worlds, key=lambda w: w.created_at)

    # No world exists — create one
    return create_world(agent_name)


def create_room(world_id: str, name: str = "general") -> Room | None:
    """Create a new room within a world.

    Args:
        world_id: The world to add the room to.
        name: A human-readable name for the room.

    Returns:
        The newly created Room, or None if the world doesn't exist.
    """
    _load_worlds()

    world = _worlds.get(world_id)
    if not world:
        logger.warning("World '%s' not found", world_id)
        return None

    now = datetime.now(timezone.utc).isoformat()
    room = Room(
        id=uuid.uuid4().hex[:12],
        name=name,
        world_id=world_id,
        agent_name=world.agent_name,
        created_at=now,
    )
    world.rooms[room.id] = room
    _save_worlds()

    logger.info("Created room '%s' in world '%s'", room.id, world_id)
    return room


def get_room(world_id: str, room_id: str) -> Room | None:
    """Get a specific room by world and room IDs.

    Args:
        world_id: The world containing the room.
        room_id: The room identifier.

    Returns:
        The Room, or None if not found.
    """
    _load_worlds()

    world = _worlds.get(world_id)
    if not world:
        return None
    return world.rooms.get(room_id)


def send_to_room(
    world_id: str,
    room_id: str,
    role: str,
    content: str,
) -> bool:
    """Add a message to a room.

    Args:
        world_id: The world containing the room.
        room_id: The room to send the message to.
        role: Message role ('user', 'assistant', 'system').
        content: The message text.

    Returns:
        True if the message was added, False if the room wasn't found.
    """
    _load_worlds()

    room = get_room(world_id, room_id)
    if not room:
        logger.warning("Room '%s' not found in world '%s'", room_id, world_id)
        return False

    room.messages.append({
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Trim to last 200 messages
    if len(room.messages) > 200:
        room.messages = room.messages[-200:]

    _save_worlds()
    return True


def get_room_context(world_id: str, room_id: str) -> list[dict[str, str]]:
    """Get all messages from a specific room.

    Args:
        world_id: The world containing the room.
        room_id: The room to get messages from.

    Returns:
        List of message dicts with 'role', 'content', 'timestamp' keys.
    """
    _load_worlds()

    room = get_room(world_id, room_id)
    if not room:
        return []
    return list(room.messages)


def list_worlds() -> list[dict[str, Any]]:
    """List all worlds with metadata.

    Returns:
        List of dicts with world info including room counts.
    """
    _load_worlds()

    result = []
    for world in _worlds.values():
        result.append({
            "id": world.id,
            "name": world.name,
            "agent_name": world.agent_name,
            "rooms_count": len(world.rooms),
            "created_at": world.created_at,
        })
    return sorted(result, key=lambda w: w.get("created_at", ""), reverse=True)


def list_rooms(world_id: str) -> list[dict[str, Any]]:
    """List all rooms in a world.

    Args:
        world_id: The world to list rooms for.

    Returns:
        List of dicts with room info including message counts.
    """
    _load_worlds()

    world = _worlds.get(world_id)
    if not world:
        return []

    result = []
    for room in world.rooms.values():
        result.append({
            "id": room.id,
            "name": room.name,
            "world_id": room.world_id,
            "agent_name": room.agent_name,
            "message_count": len(room.messages),
            "created_at": room.created_at,
        })
    return sorted(result, key=lambda r: r.get("created_at", ""), reverse=True)


def delete_world(world_id: str) -> bool:
    """Delete a world and all its rooms.

    Args:
        world_id: The world to delete.

    Returns:
        True if deleted, False if not found.
    """
    _load_worlds()

    if world_id in _worlds:
        del _worlds[world_id]
        _save_worlds()
        logger.info("Deleted world '%s'", world_id)
        return True
    return False


def delete_room(world_id: str, room_id: str) -> bool:
    """Delete a room from a world.

    Args:
        world_id: The world containing the room.
        room_id: The room to delete.

    Returns:
        True if deleted, False if not found.
    """
    _load_worlds()

    world = _worlds.get(world_id)
    if not world:
        return False

    if room_id in world.rooms:
        del world.rooms[room_id]
        _save_worlds()
        logger.info("Deleted room '%s' from world '%s'", room_id, world_id)
        return True
    return False
