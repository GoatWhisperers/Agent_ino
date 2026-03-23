# Agent_ino — Abstract del Progetto

> Valutazione dopo la sessione Snake Definitivo (2026-03-23)

---

## Cosa funziona bene

- **M40 come generatore di codice** è sorprendentemente capace. Con le istruzioni giuste (anti-pattern espliciti, pseudocodice preciso) genera codice Arduino corretto al primo colpo — S1 e S3 a 0 errori.
- **Il loop compile→upload→serial** è robusto. Rileva errori reali sull'hardware fisico, non simulati.
- **KB con lessons** riduce i bug ricorrenti tra sessioni. Il sistema impara dai suoi errori passati.
- **MI50 come orchestratore** regge — capisce il flusso, corregge errori autonomamente (es: grab_frames dimenticato → si corregge da solo).

---

## Limiti reali osservati

- **Troppo lento per task complessi.** Ogni step MI50 impiega 10-30 min con thinking. Un task Snake completo = 1-2 ore. Non scalabile per progetti grandi.
- **M40 non ragiona, esegue.** Se la spec è ambigua o incompleta, genera codice plausibile ma sbagliato (S2: physics invertita). Richiede spec quasi eseguibile per funzionare bene.
- **Visual evaluation debole.** La webcam/PIL non distingue fisica corretta da fisica rotta. Il serial è l'unico segnale affidabile. Per task senza output seriale chiaramente strutturato, la valutazione è cieca.
- **Nessuna vera comprensione del dominio.** Il programmatore non "capisce" che un serpente che muore ogni frame è rotto — vede solo se il codice compila.

---

## Per cosa lo usi concretamente

| Caso d'uso | Giudizio |
|---|---|
| Prototipare sketch Arduino da zero con spec chiara | ✅ Funziona bene |
| Fare variazioni su un progetto già funzionante | ✅ Ottimo |
| Generare codice ripetitivo (display, sensori, stati) | ✅ Forte |
| Debug autonomo di errori di compilazione | ✅ Si corregge da solo |
| Task con logica di gioco/fisica complessa | ⚠️ Fragile senza spec molto dettagliata |
| Valutare correttezza visiva complessa | ❌ Non abbastanza affidabile |
| Progetto software grande e multi-file | ❌ Non è questo il dominio |

---

## Il vero valore

**Abbassa il costo del "primo tentativo".** Per un progetto Arduino nuovo, invece di scrivere 200 righe di boilerplate, il sistema genera una base funzionante in 1-2 ore — poi tu la rifi con cognizione. Non sostituisce il programmatore umano, ma toglie il lavoro noioso e accelera l'esplorazione.
