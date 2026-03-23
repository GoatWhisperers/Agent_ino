#!/usr/bin/env python3
"""
Importa lessons da un file JSON nella KB di Agent_ino.

Uso:
    source .venv/bin/activate
    python knowledge/import_lessons.py <file.json>

Il JSON deve essere un array di oggetti con campi:
    task_type, lesson, spec_hint (opt), hardware_quirk (opt), board (opt)

Genera il JSON con il prompt in: docs/prompt_genera_lessons_kb.md
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from knowledge.db import add_lesson


def main():
    if len(sys.argv) < 2:
        print("Uso: python knowledge/import_lessons.py <file.json>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File non trovato: {path}")
        sys.exit(1)

    with open(path) as f:
        lessons = json.load(f)

    if not isinstance(lessons, list):
        print("Il JSON deve essere un array []")
        sys.exit(1)

    print(f"Importo {len(lessons)} lessons da {path.name}...\n")

    ok = 0
    for i, l in enumerate(lessons):
        try:
            add_lesson(
                task_type=l["task_type"],
                lesson=l["lesson"],
                spec_hint=l.get("spec_hint"),
                hardware_quirk=l.get("hardware_quirk"),
                board=l.get("board", ""),
            )
            ok += 1
            print(f"  ✓ [{l['task_type']}] {l['lesson'][:70]}...")
        except KeyError as e:
            print(f"  ✗ [{i}] campo mancante: {e} — skipped")
        except Exception as e:
            print(f"  ✗ [{i}] {e}")

    print(f"\n{ok}/{len(lessons)} lessons importate con successo")


if __name__ == "__main__":
    main()
