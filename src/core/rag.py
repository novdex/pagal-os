"""RAG (Retrieval-Augmented Generation) — let agents answer questions from your documents.

Upload PDFs, text files, or paste content. The system chunks the text, creates
embeddings (via Ollama or a simple TF-IDF fallback), stores them in SQLite, and
retrieves relevant chunks when agents need context.

No external vector database required — uses SQLite + cosine similarity.
"""

import hashlib
import json
import logging
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

_DB_PATH = Path.home() / ".pagal-os" / "pagal.db"

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    try:
        from src.core.database import get_connection
        return get_connection()
    except Exception:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn


def init_rag_db() -> None:
    """Create the RAG tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rag_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL DEFAULT '_global',
            filename TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            chunk_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER REFERENCES rag_documents(id) ON DELETE CASCADE,
            agent_name TEXT NOT NULL DEFAULT '_global',
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_rag_chunks_agent ON rag_chunks(agent_name);
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks by sentence boundaries.

    Falls back to word-boundary splitting when sentences are longer than
    chunk_size (e.g. plain text without punctuation).

    Args:
        text: Full document text.
        chunk_size: Target characters per chunk.
        overlap: Overlap characters between chunks.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return [text[:chunk_size] if text else ""]

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        # If a single sentence exceeds chunk_size, split it by words
        if len(sentence) > chunk_size:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            words = sentence.split()
            sub = ""
            for word in words:
                if len(sub) + len(word) + 1 > chunk_size and sub:
                    chunks.append(sub.strip())
                    # Overlap: keep last few words
                    keep = sub.split()[-overlap // 6:] if sub.split() else []
                    sub = " ".join(keep) + " " + word
                else:
                    sub += " " + word if sub else word
            if sub.strip():
                current = sub
            continue

        if len(current) + len(sentence) > chunk_size and current:
            chunks.append(current.strip())
            # Keep overlap from end of current chunk
            words = current.split()
            overlap_text = " ".join(words[-overlap // 5:]) if words else ""
            current = overlap_text + " " + sentence
        else:
            current += " " + sentence if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:chunk_size] if text else ""]


# ---------------------------------------------------------------------------
# Simple TF-IDF embedding (no external dependencies)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer."""
    return re.findall(r'\b\w+\b', text.lower())


def _compute_tfidf(text: str, vocab: dict[str, int] | None = None) -> list[float]:
    """Compute a simple TF vector for text against a vocabulary.

    For local use without ML libraries, this provides decent retrieval.
    """
    tokens = _tokenize(text)
    if not tokens:
        return []

    # Build/use vocabulary
    if vocab is None:
        unique = sorted(set(tokens))
        vocab = {w: i for i, w in enumerate(unique)}

    vec = [0.0] * len(vocab)
    for token in tokens:
        if token in vocab:
            vec[vocab[token]] += 1.0

    # Normalize
    magnitude = math.sqrt(sum(v * v for v in vec))
    if magnitude > 0:
        vec = [v / magnitude for v in vec]

    return vec


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot  # Vectors are already normalized


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ingest_document(
    filepath: str,
    agent_name: str = "_global",
    chunk_size: int = 500,
) -> dict[str, Any]:
    """Ingest a document (PDF or text) into the RAG knowledge base.

    Args:
        filepath: Path to the file to ingest.
        agent_name: Agent to associate the document with (default: all agents).
        chunk_size: Target chunk size in characters.

    Returns:
        Dict with 'ok', 'filename', 'chunks' count.
    """
    try:
        init_rag_db()
        path = Path(filepath).expanduser().resolve()

        # Path boundary check — reuse the same sandbox as file tools
        from src.tools.files import _is_path_allowed
        access_error = _is_path_allowed(path)
        if access_error:
            return {"ok": False, "error": access_error}

        if not path.exists():
            return {"ok": False, "error": f"File not found: {filepath}"}

        # Read content based on file type
        if path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError:
                return {"ok": False, "error": "pypdf package required for PDF files"}
        else:
            text = path.read_text(encoding="utf-8", errors="replace")

        if not text.strip():
            return {"ok": False, "error": "Document is empty"}

        # Check for duplicate
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        conn = _get_conn()
        try:
            existing = conn.execute(
                "SELECT id FROM rag_documents WHERE content_hash = ? AND agent_name = ?",
                (content_hash, agent_name),
            ).fetchone()
            if existing:
                return {"ok": True, "filename": path.name, "chunks": 0, "message": "Document already ingested"}

            # Chunk the text
            chunks = _chunk_text(text, chunk_size=chunk_size)

            # Store document
            cursor = conn.execute(
                "INSERT INTO rag_documents (agent_name, filename, content_hash, chunk_count) VALUES (?, ?, ?, ?)",
                (agent_name, path.name, content_hash, len(chunks)),
            )
            doc_id = cursor.lastrowid

            # Store chunks
            for i, chunk in enumerate(chunks):
                conn.execute(
                    "INSERT INTO rag_chunks (doc_id, agent_name, chunk_index, content) VALUES (?, ?, ?, ?)",
                    (doc_id, agent_name, i, chunk),
                )

            conn.commit()
            logger.info("Ingested '%s': %d chunks for agent '%s'", path.name, len(chunks), agent_name)
            return {"ok": True, "filename": path.name, "chunks": len(chunks)}
        finally:
            conn.close()

    except Exception as e:
        logger.error("RAG ingest failed: %s", e)
        return {"ok": False, "error": str(e)}


def ingest_text(
    content: str,
    title: str = "pasted_text",
    agent_name: str = "_global",
) -> dict[str, Any]:
    """Ingest raw text content into the RAG knowledge base.

    Args:
        content: The text content to ingest.
        title: A title/name for the content.
        agent_name: Agent to associate with.

    Returns:
        Dict with 'ok', 'filename', 'chunks' count.
    """
    try:
        init_rag_db()

        if not content.strip():
            return {"ok": False, "error": "Content is empty"}

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        conn = _get_conn()
        try:
            existing = conn.execute(
                "SELECT id FROM rag_documents WHERE content_hash = ? AND agent_name = ?",
                (content_hash, agent_name),
            ).fetchone()
            if existing:
                return {"ok": True, "filename": title, "chunks": 0, "message": "Content already ingested"}

            chunks = _chunk_text(content)

            cursor = conn.execute(
                "INSERT INTO rag_documents (agent_name, filename, content_hash, chunk_count) VALUES (?, ?, ?, ?)",
                (agent_name, title, content_hash, len(chunks)),
            )
            doc_id = cursor.lastrowid

            for i, chunk in enumerate(chunks):
                conn.execute(
                    "INSERT INTO rag_chunks (doc_id, agent_name, chunk_index, content) VALUES (?, ?, ?, ?)",
                    (doc_id, agent_name, i, chunk),
                )

            conn.commit()
            return {"ok": True, "filename": title, "chunks": len(chunks)}
        finally:
            conn.close()

    except Exception as e:
        return {"ok": False, "error": str(e)}


def query_documents(
    query: str,
    agent_name: str = "_global",
    top_k: int = 5,
) -> dict[str, Any]:
    """Search the RAG knowledge base for chunks relevant to a query.

    Uses keyword matching with TF-IDF scoring for local retrieval.

    Args:
        query: The search query.
        agent_name: Agent whose documents to search (also searches _global).
        top_k: Number of top results to return.

    Returns:
        Dict with 'ok', 'results' (list of {content, score, filename}).
    """
    try:
        init_rag_db()
        conn = _get_conn()
        try:
            # Get all chunks for this agent + global
            rows = conn.execute(
                """SELECT c.content, c.doc_id, d.filename
                   FROM rag_chunks c
                   JOIN rag_documents d ON c.doc_id = d.id
                   WHERE c.agent_name IN (?, '_global')
                   ORDER BY c.id""",
                (agent_name,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return {"ok": True, "results": [], "message": "No documents ingested yet"}

        # Build vocabulary from all chunks + query
        all_texts = [row["content"] for row in rows] + [query]
        all_tokens = set()
        for text in all_texts:
            all_tokens.update(_tokenize(text))
        vocab = {w: i for i, w in enumerate(sorted(all_tokens))}

        # Compute query vector
        query_vec = _compute_tfidf(query, vocab)

        # Score each chunk
        scored: list[tuple[float, str, str]] = []
        for row in rows:
            chunk_vec = _compute_tfidf(row["content"], vocab)
            score = _cosine_similarity(query_vec, chunk_vec)
            if score > 0.01:
                scored.append((score, row["content"], row["filename"]))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        results = [
            {"content": content, "score": round(score, 4), "filename": filename}
            for score, content, filename in scored[:top_k]
        ]

        return {"ok": True, "results": results}

    except Exception as e:
        logger.error("RAG query failed: %s", e)
        return {"ok": False, "error": str(e)}


def list_documents(agent_name: str = "_global") -> dict[str, Any]:
    """List all ingested documents.

    Args:
        agent_name: Filter by agent (also includes _global).

    Returns:
        Dict with 'ok' and 'documents' list.
    """
    try:
        init_rag_db()
        conn = _get_conn()
        rows = conn.execute(
            """SELECT id, agent_name, filename, chunk_count, created_at
               FROM rag_documents
               WHERE agent_name IN (?, '_global')
               ORDER BY created_at DESC""",
            (agent_name,),
        ).fetchall()
        conn.close()

        docs = [dict(row) for row in rows]
        return {"ok": True, "documents": docs}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def delete_document(doc_id: int) -> dict[str, Any]:
    """Delete a document and its chunks from the RAG store.

    Args:
        doc_id: The document ID to delete.

    Returns:
        Dict with 'ok' status.
    """
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM rag_chunks WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM rag_documents WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "message": f"Document {doc_id} deleted"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
