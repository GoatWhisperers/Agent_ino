import sys
sys.path.insert(0, '/home/lele/codex-openai/programmatore_di_arduini')

from knowledge.db import init_db, add_snippet, search_snippets_text
from knowledge.semantic import index_snippet, search_snippets
from knowledge.query_engine import get_context_for_task

# Init
init_db()

# Aggiungi uno snippet di test
sid = add_snippet(
    task="far lampeggiare LED sul pin 13",
    code='void setup(){pinMode(13,OUTPUT);}\nvoid loop(){digitalWrite(13,HIGH);delay(500);digitalWrite(13,LOW);delay(500);}',
    board="arduino:avr:uno",
    libraries=[],
    tags=["led", "blink", "base"]
)
print(f"Snippet aggiunto: {sid}")

# Indicizza in ChromaDB
index_snippet(sid, "far lampeggiare LED sul pin 13", 'void setup()...', ["led", "blink"])

# Cerca
results = search_snippets("accendere e spegnere un LED")
print(f"Risultati semantici: {len(results)}")
for r in results:
    print(f"  - {r['task_description']} (dist: {r.get('distance', '?')})")

# Contesto per task
ctx = get_context_for_task("voglio far lampeggiare un LED rosso")
print(f"\nContesto:\n{ctx}")
