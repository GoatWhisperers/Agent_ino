"""
Query engine: combina ricerca semantica e strutturata.
Ritorna contesto pronto per essere usato dall'agente.
"""
from pathlib import Path
from typing import List, Dict

from knowledge.db import (
    search_snippets_text,
    search_libraries,
    get_error_fixes,
    get_snippet,
)
from knowledge.semantic import search_snippets as semantic_search_snippets


def find_relevant_context(query: str, mode: str = "NEW") -> dict:
    """
    Data una query in linguaggio naturale, cerca:
    - snippet semanticamente simili
    - librerie rilevanti per keyword
    - fix di errori noti

    Ritorna dict con:
    {
        "snippets": [...],      # max 3 snippet più simili
        "libraries": [...],     # librerie rilevanti
        "error_fixes": [...],   # fix noti per errori simili
        "summary": str          # testo riassuntivo del contesto trovato
    }
    """
    # 1. Snippet semantici
    semantic_results = semantic_search_snippets(query, n=5)
    # Arricchisci con il codice completo dal DB
    snippets = []
    for r in semantic_results[:3]:
        full = get_snippet(r["id"])
        if full:
            full["distance"] = r.get("distance")
            snippets.append(full)

    # Fallback: ricerca testuale se semantica non restituisce nulla
    if not snippets:
        text_results = search_snippets_text(query, limit=3)
        snippets = text_results

    # 2. Librerie rilevanti — estrai keyword dalla query
    keywords = _extract_keywords(query)
    libraries = []
    seen_libs = set()
    for kw in keywords:
        for lib in search_libraries(kw):
            if lib["name"] not in seen_libs:
                libraries.append(lib)
                seen_libs.add(lib["name"])

    # 3. Fix di errori noti (tutti, ordinati per confirmed_count)
    error_fixes = get_error_fixes(limit=5)

    # 4. Summary
    summary_parts = []
    if snippets:
        summary_parts.append(f"{len(snippets)} snippet simili trovati")
    if libraries:
        names = ", ".join(l["name"] for l in libraries[:3])
        summary_parts.append(f"librerie rilevanti: {names}")
    if error_fixes:
        summary_parts.append(f"{len(error_fixes)} fix di errori noti disponibili")
    summary = "; ".join(summary_parts) if summary_parts else "nessun contesto trovato"

    return {
        "snippets": snippets,
        "libraries": libraries[:5],
        "error_fixes": error_fixes,
        "summary": summary,
    }


def find_similar_code(task: str) -> List[Dict]:
    """
    Cerca codice simile nel DB e nei completed/.
    Ritorna lista di {path, task, similarity}.
    """
    results = []

    # Cerca negli snippet del DB
    semantic_hits = semantic_search_snippets(task, n=5)
    for hit in semantic_hits:
        results.append(
            {
                "path": f"db://snippets/{hit['id']}",
                "task": hit.get("task_description", ""),
                "similarity": 1.0 - (hit.get("distance") or 0.0),
            }
        )

    # Cerca nei file completed/ se la directory esiste
    base = Path(__file__).parent.parent
    completed_dir = base / "completed"
    if completed_dir.exists():
        for f in sorted(completed_dir.iterdir()):
            if f.is_dir():
                sketch_file = f / f"{f.name}.ino"
                if not sketch_file.exists():
                    # Cerca qualsiasi .ino
                    inos = list(f.glob("*.ino"))
                    sketch_file = inos[0] if inos else None
                if sketch_file and sketch_file.exists():
                    results.append(
                        {
                            "path": str(sketch_file),
                            "task": f.name.replace("_", " "),
                            "similarity": 0.3,  # similarity di default per file locali
                        }
                    )

    return results


def get_context_for_task(task: str) -> str:
    """
    Ritorna una stringa di contesto pronta da inserire nel prompt del LLM.

    Formato:
    === CONTESTO DAL DATABASE ===
    [Snippet simile trovato: <descrizione>]
    <codice>
    ...
    [Libreria rilevante: DHT sensor library]
    ...
    """
    ctx = find_relevant_context(task)

    lines = ["=== CONTESTO DAL DATABASE ==="]

    # Snippet
    for s in ctx["snippets"]:
        dist_str = ""
        if s.get("distance") is not None:
            dist_str = f" (distanza: {s['distance']:.3f})"
        lines.append(f"\n[Snippet simile trovato: {s['task_description']}{dist_str}]")
        lines.append("```cpp")
        lines.append(s.get("code", ""))
        lines.append("```")

    # Librerie
    for lib in ctx["libraries"]:
        desc = lib.get("description") or ""
        lines.append(f"\n[Libreria rilevante: {lib['name']}] {desc}")
        if lib.get("include_header"):
            lines.append(f"  Include: {lib['include_header']}")
        if lib.get("install_cmd"):
            lines.append(f"  Installa: {lib['install_cmd']}")
        if lib.get("example_code"):
            lines.append(f"  Esempio:")
            lines.append("  ```cpp")
            lines.append(f"  {lib['example_code'][:300]}")
            lines.append("  ```")

    # Fix errori noti
    if ctx["error_fixes"]:
        lines.append("\n[Errori comuni e fix noti]")
        for fix in ctx["error_fixes"][:3]:
            lines.append(f"  Errore: {fix['error_pattern']}")
            if fix.get("cause"):
                lines.append(f"  Causa: {fix['cause']}")
            if fix.get("fix_description"):
                lines.append(f"  Fix: {fix['fix_description']}")

    if len(lines) == 1:
        lines.append("Nessun contesto rilevante trovato nel database.")

    return "\n".join(lines)


# ── Helpers ────────────────────────────────────────────────

def _extract_keywords(text: str) -> List[str]:
    """Estrae keyword semplici dal testo (parole significative)."""
    # Lista di stopwords italiane e inglesi minima
    stopwords = {
        "un", "una", "il", "la", "lo", "i", "gli", "le", "di", "da", "in",
        "con", "su", "per", "tra", "fra", "che", "e", "o", "ma", "se",
        "a", "al", "del", "della", "dei", "degli", "delle", "nel", "nella",
        "the", "a", "an", "of", "for", "to", "in", "on", "at", "by",
        "fare", "far", "usare", "uso", "voglio", "vorrei", "come",
        "questo", "questa", "questi", "queste",
    }
    words = text.lower().split()
    keywords = []
    for w in words:
        # Rimuovi punteggiatura
        w = w.strip(".,;:!?()[]\"'")
        if len(w) >= 3 and w not in stopwords:
            keywords.append(w)
    return list(dict.fromkeys(keywords))  # deduplica mantenendo ordine
