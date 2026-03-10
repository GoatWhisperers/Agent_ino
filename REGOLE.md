# Regole — Programmatore di Arduini

Regole operative del progetto. Ogni regola nasce da un'esperienza concreta.

---

## Regola 1 — Il codice prodotto dai modelli va ripulito prima di compilare

Il codice generato dai LLM (sia MI50 che M40) contiene elementi che non fanno
parte del sorgente Arduino e che devono essere rimossi prima di passarlo al
compilatore:

- Blocchi di ragionamento interno: `<think>...</think>` (Qwen3.5 su MI50)
- Marcatori markdown: ` ```cpp `, ` ``` `, ` ```arduino `
- Testo narrativo prima e dopo il codice ("Ecco lo sketch:", "Spiegazione:", ecc.)
- Tabelle, elenchi puntati, note a margine
- Commenti in linguaggio naturale fuori dal codice

Il testo completo prodotto dal modello va sempre conservato integralmente:
- Il blocco `<think>...</think>` rimane visibile e viene salvato — il percorso
  di ragionamento è un dato prezioso, può rivelare perché il modello ha scelto
  un approccio, quali alternative ha considerato, dove ha avuto dubbi.
- Il thinking può essere oggetto di analisi, confronto tra run, o input per
  iterazioni successive.

Solo il codice estratto e ripulito viene passato al compilatore.
Il resto non si butta.

---

## Regola 2 — Prima di scrivere, cerca cosa esiste

L'agente non parte mai da zero senza aver prima cercato:
- Nel database di snippet: codice simile per funzione o librerie
- Nella cartella `completed/`: progetti finiti con obiettivo analogo
- Nella documentazione: librerie già note che risolvono il problema

Se trova qualcosa di pertinente, lo analizza e lo usa come punto di partenza.
Il codice trovato viene letto, compreso e adattato — non copiato ciecamente.

---

## Regola 3 — CONTINUE e MODIFY non sono task nuovi

Se il task riguarda un progetto esistente:
- L'agente legge prima tutto il codice presente nel workspace
- Legge i log dell'ultima run per capire lo stato
- Produce un "resoconto dello stato" prima di procedere
- Non riscrive da zero quello che già funziona

---
