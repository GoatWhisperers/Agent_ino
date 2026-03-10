# Strategia thinking — MI50 e M40

Qwen3.5-9B supporta il "thinking mode": prima di rispondere produce un blocco
`<think>...</think>` con ragionamento interno. Questo migliora la qualità della risposta
ma può costare 5-15 minuti per risposta complessa.

La regola è semplice: **thinking solo dove serve davvero decidere qualcosa di non ovvio.**

---

## Mappa fase → thinking

| Fase | Componente | Modello | Thinking | Motivo |
|------|-----------|---------|----------|--------|
| 0 — Analyst (NEW) | `analyst.py` `_SIMILAR_SYSTEM` | MI50 | ❌ `/no_think` | Compito meccanico: riassumi snippet, non serve ragionamento |
| 0 — Analyst (CONTINUE) | `analyst.py` `_PROJECT_STATE_SYSTEM` | MI50 | ❌ `/no_think` | Output JSON fisso, la struttura è vincolata |
| 0 — Analyst (MODIFY) | `analyst.py` `_MODIFY_SYSTEM` | MI50 | ❌ `/no_think` | Output JSON fisso |
| 1 — plan_task | `orchestrator.py` `_PLAN_SYSTEM` | MI50 | ❌ `/no_think` | Output JSON, già impostato |
| 1b — plan_functions | `orchestrator.py` `_PLAN_FUNCTIONS_SYSTEM` | MI50 | ❌ `/no_think` | Output JSON, già impostato |
| 2 — generate_globals | `generator.py` `SYSTEM_GLOBALS` | M40 | ❌ `/no_think` | Scrivi include/define: zero ambiguità |
| 2 — generate_function | `generator.py` `SYSTEM_FUNCTION` | M40 | ❌ `/no_think` | Scrivi una funzione: compito meccanico |
| 2 — generate_code (monolitico) | `generator.py` `SYSTEM_PROMPT` | M40 | ❌ `/no_think` | Stesso motivo |
| 2b — patch_code | `generator.py` `SYSTEM_PROMPT` | M40 | ❌ `/no_think` | MI50 ha già analizzato l'errore, M40 esegue |
| 3a — analyze_errors | `orchestrator.py` `_ANALYZE_ERRORS_SYSTEM` | MI50 | ❌ `/no_think` | Output JSON, già impostato |
| 5 — evaluate (seriale) | `evaluator.py` | MI50 | ✅ thinking | Deve ragionare: output seriale ambiguo, decisione non ovvia |
| 5 — evaluate_visual | `evaluator.py` | MI50 | ✅ thinking | Guarda frame webcam e decide: massima difficoltà cognitiva |

---

## Come si attiva `/no_think`

Il token `/no_think` all'inizio del system prompt istruisce Qwen3.5 a saltare il blocco
`<think>...</think>` e rispondere direttamente.

```python
SYSTEM_GLOBALS = """/no_think
Sei un esperto programmatore Arduino.
Genera SOLO la sezione globals...
"""
```

Se il modello ignora il token (raro), il client estrae e scarta comunque il thinking con
`_extract_thinking()` prima di usare la risposta.

---

## Impatto sulle performance

Senza `/no_think`, MI50 in modalità thinking tipicamente:
- Produce 500-2000 token di ragionamento interno
- Impiega 5-15 minuti per risposta
- Usa ~3 GB di VRAM in più durante il prefill

Con `/no_think`:
- Risposta diretta in 10-60 secondi
- VRAM costante

**Risparmio pratico per una run completa:**
- Fase 0 (Analyst): da ~8 min a ~15 sec
- Fase 1 (già `/no_think`): invariato
- Fase 2 M40 (già veloce): leggero miglioramento
- Fase 5 (Evaluator): invariato — thinking rimane attivo

Una run completa scende da ~45-60 min a ~20-30 min grazie a questi cambiamenti.

---

## Quando tornare ad abilitare il thinking

Se la qualità del codice generato da M40 peggiora (bug ricorrenti, logica sbagliata),
rimuovere `/no_think` da `SYSTEM_FUNCTION` in `generator.py` e osservare se migliora.

Il thinking su M40 è meno impattante che su MI50 perché M40 è più veloce (~33 tok/s
vs ~2-5 tok/s di MI50), quindi il costo è più basso.

---

## Note tecniche

- Il token `/no_think` funziona sia su MI50 (PyTorch/transformers) che su M40 (llama.cpp)
- llama.cpp supporta anche il parametro API `"thinking": false` nel payload JSON —
  ma il token nel system prompt è più robusto perché funziona su tutti i backend
- Il thinking viene sempre estratto e loggato nel JSONL anche quando attivo —
  non viene mai perso, può essere analizzato in post per debug
