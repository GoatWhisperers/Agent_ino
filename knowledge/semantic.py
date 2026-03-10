"""
Ricerca semantica tramite ChromaDB + sentence-transformers.
"""
from pathlib import Path
from typing import List, Dict

import chromadb

CHROMA_PATH = str(Path(__file__).parent / "chroma")

# ── Embedding function ─────────────────────────────────────
def _get_ef():
    """
    Ritorna l'embedding function.
    Prova prima SentenceTransformerEmbeddingFunction con all-MiniLM-L6-v2,
    fallback a DefaultEmbeddingFunction se sentence_transformers non è disponibile.
    """
    try:
        from chromadb.utils.embedding_functions import (
            SentenceTransformerEmbeddingFunction,
        )
        return SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2",
            device="cpu",
        )
    except Exception:
        try:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            return DefaultEmbeddingFunction()
        except Exception:
            return None


# Singleton client e ef
_client = None
_ef = None


def _get_client() -> chromadb.ClientAPI:
    """Ritorna (o crea) il client ChromaDB persistente."""
    global _client
    if _client is None:
        Path(CHROMA_PATH).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _client


def _get_embedding_function():
    """Ritorna (o crea) l'embedding function singleton."""
    global _ef
    if _ef is None:
        _ef = _get_ef()
    return _ef


def get_collection(name: str):
    """Crea o recupera una collection ChromaDB con l'embedding function configurata."""
    client = _get_client()
    ef = _get_embedding_function()
    kwargs = {"name": name}
    if ef is not None:
        kwargs["embedding_function"] = ef
    return client.get_or_create_collection(**kwargs)


# ── Indicizzazione ─────────────────────────────────────────

def index_snippet(
    sid: str,
    task_description: str,
    code: str,
    tags: List[str],
) -> None:
    """
    Indicizza uno snippet nella collection 'snippets'.
    Il documento indicizzato è la concatenazione di task + code (troncato).
    """
    collection = get_collection("snippets")
    # Tronca il codice per non sovraccaricare l'embedding
    code_preview = code[:500] if code else ""
    document = f"{task_description}\n\n{code_preview}"
    metadata = {
        "task_description": task_description,
        "tags": ",".join(tags) if tags else "",
    }
    # upsert: aggiorna se già esiste
    collection.upsert(
        ids=[sid],
        documents=[document],
        metadatas=[metadata],
    )


def index_doc(
    doc_id: str,
    title: str,
    content: str,
    source: str,
) -> None:
    """Indicizza un documento di documentazione nella collection 'docs'."""
    collection = get_collection("docs")
    document = f"{title}\n\n{content[:1000]}"
    metadata = {
        "title": title,
        "source": source,
    }
    collection.upsert(
        ids=[doc_id],
        documents=[document],
        metadatas=[metadata],
    )


# ── Ricerca ────────────────────────────────────────────────

def search_snippets(query: str, n: int = 5) -> List[Dict]:
    """
    Cerca snippet semanticamente simili alla query.

    Ritorna una lista di dict con:
      - id, task_description, tags, distance
    """
    collection = get_collection("snippets")
    try:
        count = collection.count()
    except Exception:
        count = 0
    if count == 0:
        return []

    n_actual = min(n, count)
    results = collection.query(
        query_texts=[query],
        n_results=n_actual,
        include=["metadatas", "distances"],
    )
    output = []
    if results and results.get("ids") and results["ids"][0]:
        for i, rid in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            dist = results["distances"][0][i] if results.get("distances") else None
            output.append(
                {
                    "id": rid,
                    "task_description": meta.get("task_description", ""),
                    "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
                    "distance": dist,
                }
            )
    return output


def search_docs(query: str, n: int = 3) -> List[Dict]:
    """
    Cerca documentazione semanticamente simile alla query.

    Ritorna una lista di dict con: id, title, source, distance
    """
    collection = get_collection("docs")
    try:
        count = collection.count()
    except Exception:
        count = 0
    if count == 0:
        return []

    n_actual = min(n, count)
    results = collection.query(
        query_texts=[query],
        n_results=n_actual,
        include=["metadatas", "distances"],
    )
    output = []
    if results and results.get("ids") and results["ids"][0]:
        for i, rid in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            dist = results["distances"][0][i] if results.get("distances") else None
            output.append(
                {
                    "id": rid,
                    "title": meta.get("title", ""),
                    "source": meta.get("source", ""),
                    "distance": dist,
                }
            )
    return output


def remove_snippet(sid: str) -> None:
    """Rimuove uno snippet dall'indice semantico."""
    collection = get_collection("snippets")
    try:
        collection.delete(ids=[sid])
    except Exception:
        pass
