# TODO — Programmatore di Arduini

> Aggiornato: 2026-03-22

---

## 🟡 Dashboard — miglioramenti UI (dopo Snake)

- [ ] **Layout**: finestra in alto troppo grande, quelle sotto quasi invisibili — redistribuire spazio
- [ ] **M40 token stream**: i token emessi da M40 non sono visibili nella dashboard
- [ ] **Thinking visibile**: reasoning MI50 da mostrare in azzurro, testo normale in bianco
- [ ] **Pannelli ridimensionabili**: drag handle tra i pannelli
- [ ] **Scroll testi e immagini**: i contenuti lunghi devono essere scrollabili dentro il pannello

---

## 🔴 Priorità alta — prossima sessione

- [ ] **Skill library** — indicizzare funzioni Arduino testate come skill riutilizzabili
  - `knowledge/skills.db` con funzioni nominate: `elasticCollision()`, `initOLED()`, `drawBrick()`
  - M40 riceve skill rilevanti invece di riscrivere da zero
  - Popolata automaticamente da learner dopo ogni run riuscita

- [ ] **Doc ingestion** — indicizzare documentazione Adafruit SSD1306 + ESP32 in ChromaDB
  - Script che legge README/datasheet e indicizza API, firme, esempi
  - MI50 interroga: "firma corretta di getTextBounds?" invece di hallucinarla
  - Base per il sistema "legge libri" discusso

- [ ] **Fix fisica tre palline** — caricare `workspace/tre_palline_fix/tre_palline_fix.ino`
  - Usa float + impulso<0 + overlap resolution
  - Sostituisce T4 in KB con versione fisica corretta

- [ ] **eth0 netplan permanente** — evitare `sudo ip route add` manuale ad ogni reboot
  ```bash
  # /etc/netplan/... aggiungere eth0 dhcp4: yes
  ```

---

## 🟡 Medio termine

- [ ] **Coppie contrastive** (ispirato RLHF leggero)
  - Salvare "questa task description ha funzionato / questa no" per lo stesso task
  - Few-shot examples per MI50 senza fine-tuning

- [ ] **MemGPT summarization** — quando i turni superano N token, MI50 riassume
  - Previene context overflow su run lunghe (>30 min)
  - Attualmente i turni vecchi vengono solo troncati

- [ ] **evaluate_visual più robusto** — cerchi 3-4px non rilevabili dalla webcam
  - Crop + upscale del frame prima di mandare a MI50
  - O criterio ibrido: serial output primario + visual secondario

- [ ] **vcap_frames automatico** — MI50 attiva webcam senza che il supervisore lo guidi
  - Ora va specificato esplicitamente nel task

- [ ] **Test di regressione** — suite di task standard con risultato atteso
  - "LED blink 500ms" → serial output "BLINK"
  - "Pallina rimbalzante" → serial output "BOUNCE"
  - Eseguibile con un comando per verificare che tutto funzioni dopo modifiche

---

## 🟢 Architetturale / lungo termine

- [ ] **API REST per tool_agent** — lancia task via HTTP senza terminale
- [ ] **Notifiche fine run** — Telegram/email quando la run finisce
- [ ] **Multi-board** — supporto Arduino Uno oltre a ESP32

---

## 💡 Idea grossa — da discutere

- [ ] **Server di memoria per Claude + Codex**
  - Usare questo server (MI50+M40+ChromaDB) come backend di memoria persistente
    per assistenti AI (Claude Code, Codex, altri)
  - mem0-style ma locale, con MI50 che estrae i fatti invece di OpenAI
  - Skill library condivisa tra progetti diversi
  - "Legge libri": agent che ingerisce documentazione e la rende interrogabile
  - **Vedi discussione separata**
