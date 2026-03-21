# Lezione — Sistema "lessons": primo test reale

> Data: 2026-03-20
> Obiettivo: verificare se le lessons estratte da T4 (tre palline) migliorano la qualità
> della generazione su un task più complesso (muretto), senza intervento manuale del supervisore.

---

## Il problema che le lessons risolvono

Durante T4 (tre palline), il supervisore ha iniettato manualmente 2149 caratteri di specifiche
tecniche nella task description per ottenere compilazione al primo tentativo:
- rst_pin=-1 nel costruttore SSD1306
- Wire.begin(21,22) con pin espliciti
- float per posizioni e velocità
- impulso < 0 check + overlap resolution
- clearDisplay() dentro drawBalls()
- loop() con solo update+draw

Senza queste specifiche (T1/T2/T3), M40 generava codice con fisica sbagliata o display nero.
Quella conoscenza viveva nel supervisore, non nel sistema.

**Le lessons trasferiscono questa conoscenza dal supervisore alla KB**, rendendola disponibile
automaticamente per ogni run futura simile.

---

## Implementazione

### Dove vengono salvate le lessons

```python
# knowledge/db.py
CREATE TABLE lessons (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,    # "OLED animation", "ESP32 OLED", "OLED physics"
    lesson TEXT NOT NULL,        # descrizione della lezione
    spec_hint TEXT,              # hint concreto da iniettare nel prompt
    hardware_quirk TEXT,         # quirk hardware specifico
    board TEXT DEFAULT '',
    confirmed_count INTEGER DEFAULT 1,
    created_at TEXT
);

# knowledge/semantic.py — ChromaDB collection "lessons"
# Ogni lesson è indicizzata con embedding MiniLM per retrieval semantico
```

### Come vengono estratte (learner.py)

Dopo ogni run, `learner.extract_patterns()` chiede a MI50 di estrarre lessons strutturate
dal codice e dagli errori incontrati. Schema JSON:
```json
{
  "lessons": [
    {
      "task_type": "OLED animation",
      "lesson": "drawBalls() deve contenere clearDisplay() e display.display()",
      "spec_hint": "void drawBalls() { display.clearDisplay(); ... display.display(); }",
      "hardware_quirk": ""
    }
  ]
}
```

### Come vengono iniettate (tool_agent.py)

```python
def _auto_enrich_task(sess):
    # Cerca lessons semanticamente in ChromaDB
    from knowledge.semantic import search_lessons
    results = search_lessons(query=sess.task, n=5, board=sess.fqbn)
    # Formatta come blocco testo
    sess.lessons_context = "=== LESSONS DA RUN PRECEDENTI ===\n" + ...

def _plan_task(args, sess):
    _auto_enrich_task(sess)           # recupera lessons
    context = sess.lessons_context    # inietta nel contesto
    result = orch.plan_task(task=sess.task, context=context)
    ...

def _plan_functions(args, sess):
    # Anche plan_functions riceve le lessons
    context = (context + "\n\n" + sess.lessons_context).strip()
    ...
```

---

## Risultati del primo test (task muretto)

### Lessons recuperate automaticamente (5/7 rilevanti)

| Lesson | Distanza semantica | Recepita da MI50? |
|--------|-------------------|-------------------|
| rst_pin=-1 costruttore | 0.21 | ✅ sì |
| Wire.begin(21,22) | 0.24 | ✅ sì |
| float per fisica + impulso<0 | 0.31 | ✅ sì ("impulso negativo") |
| drawBalls con clearDisplay+display | 0.33 | ✅ sì ("drawBalls()") |
| loop() solo update+draw | 0.38 | ✅ sì |

### Impatto misurabile

| Metrica | T4 (senza lessons) | Muretto (con lessons) |
|---------|-------------------|----------------------|
| Caratteri iniettati manualmente | 2149 | 0 |
| Errori compilazione primo tentativo | 0 (con specs manuali) | 0 |
| Intervento supervisore sulla task | Sì (2149 char) | No |
| "impulso negativo" nel piano | Solo perché iniettato | Autonomo |

**Conclusione: il sistema lessons funziona.** MI50 ha prodotto un piano di qualità equivalente
a T4 senza nessuna iniezione manuale.

---

## Limiti osservati

1. **Le lessons non coprono ancora i bug del tool_agent stesso** — il loop su plan_functions
   è stato scoperto in questa sessione e fixato, ma non è ancora una lesson in KB.

2. **La qualità del retrieval dipende dalla similarità semantica** — "oled" e "esp32"
   trovano lessons pertinenti, ma task molto diversi potrebbero non trovare nulla.

3. **Le lessons estratte da MI50 sono a volte troppo generiche** — "usare float per le velocità"
   è utile, ma "il costruttore SSD1306 ha rst_pin come 4° parametro, non I2C addr" è più
   specifico e più utile. Il prompt del learner dovrebbe spingere su specificity.

4. **save_to_kb non eseguito per il muretto** — la run è stata killata prima di save_to_kb.
   Le lessons del muretto non sono ancora in KB.

---

## Prossimi sviluppi

### Breve termine
- Salvare manualmente le lessons del muretto nella KB
- Aggiungere lesson "evaluate_visual inaffidabile con sfondo colorato"
- Aggiungere lesson "compilazione al primo tentativo possibile con plan_functions dettagliato"

### Medio termine
- **Coppie contrastive**: salvare anche gli esempi SBAGLIATI (con label "ANTI-PATTERN")
  così MI50 impara cosa non fare
- **Lesson confidence**: peso per `confirmed_count` — una lesson vista 5 volte pesa di più
- **Retrieval ibrido**: affiancare BM25 (keyword exact match) al semantico per nomi di API
  specifici (es. "SSD1306_SWITCHCAPVCC")

### Lungo termine
- **Skill library**: funzioni Arduino testate e complete, recuperabili come blocchi da M40
- **Pattern anti-errore**: KB di errori di compilazione già visti con fix automatico
  (già parzialmente in `fix_known_includes()` e `fix_known_api_errors()`)
