"""RAG tools — let agents ingest documents and query their knowledge base."""

from typing import Any

from src.core.rag import ingest_document, ingest_text, list_documents, query_documents
from src.tools.registry import register_tool


def tool_query_documents(query: str, agent_name: str = "_global") -> dict[str, Any]:
    """Search your uploaded documents for information relevant to a query."""
    return query_documents(query, agent_name=agent_name)


def tool_ingest_document(filepath: str, agent_name: str = "_global") -> dict[str, Any]:
    """Upload and index a document (PDF or text file) into the knowledge base."""
    return ingest_document(filepath, agent_name=agent_name)


def tool_ingest_text(content: str, title: str = "pasted_text", agent_name: str = "_global") -> dict[str, Any]:
    """Add text content directly to the knowledge base."""
    return ingest_text(content, title=title, agent_name=agent_name)


# Auto-register
register_tool(
    name="query_documents",
    function=tool_query_documents,
    description="Search your uploaded documents and knowledge base for relevant information. Use this to answer questions from PDFs, text files, or any ingested content.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The question or search query"},
            "agent_name": {"type": "string", "description": "Agent name to search docs for (default: _global)", "default": "_global"},
        },
        "required": ["query"],
    },
)

register_tool(
    name="ingest_document",
    function=tool_ingest_document,
    description="Upload and index a document (PDF or text file) into the knowledge base so it can be searched later.",
    parameters={
        "type": "object",
        "properties": {
            "filepath": {"type": "string", "description": "Path to the PDF or text file to ingest"},
            "agent_name": {"type": "string", "description": "Agent to associate with (default: _global)", "default": "_global"},
        },
        "required": ["filepath"],
    },
)

register_tool(
    name="ingest_text",
    function=tool_ingest_text,
    description="Add text content directly to the knowledge base for future search.",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The text content to add"},
            "title": {"type": "string", "description": "A name for this content", "default": "pasted_text"},
            "agent_name": {"type": "string", "description": "Agent to associate with", "default": "_global"},
        },
        "required": ["content"],
    },
)
