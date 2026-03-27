#!/usr/bin/env python3
"""
Genera lessons per la KB usando M40 e le importa automaticamente.

Uso:
    source .venv/bin/activate

    # Genera e importa lessons su un argomento
    python knowledge/generate_lessons.py "display TFT ST7735 ILI9341"

    # Genera solo JSON (senza importare) per revisione manuale
    python knowledge/generate_lessons.py "NeoPixel WS2812B" --dry-run

    # Estrai lessons da codice Arduino (file o URL GitHub)
    python knowledge/generate_lessons.py --from-code sketch.ino
    python knowledge/generate_lessons.py --from-code https://raw.githubusercontent.com/.../sketch.ino

    # Crawl di tutti i repo di un utente GitHub
    python knowledge/generate_lessons.py --github-user PaoloAliverti
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge.db import add_lesson

# ── Prompt template ───────────────────────────────────────────────────────────

PROMPT_TOPIC = """\
Sei un esperto di programmazione Arduino/ESP32 con anni di esperienza pratica.

Il tuo compito: generare una lista di "lessons" per una knowledge base di un agente
AI che genera codice Arduino. Le lessons servono a evitare bug ricorrenti e guidare
la generazione di codice corretto.

ARGOMENTO: {topic}

FORMATO: Produci SOLO un array JSON valido, senza testo prima o dopo.
Ogni elemento ha questi campi:

  "task_type"     : categoria breve in snake_case (es: "tft_display", "neopixel")
  "lesson"        : REGOLA CRITICA in maiuscolo + spiegazione. Max 400 caratteri.
                    Includi nomi esatti di funzioni/costanti/variabili.
  "spec_hint"     : anti-pattern — cosa causa il bug se non si segue la regola (può essere null)
  "hardware_quirk": nota hardware specifica (può essere null)
  "board"         : "esp32:esp32:esp32" | "arduino:avr:uno" | "" (vuoto = entrambe)

REGOLE PER LESSONS BUONE:
1. ACTIONABLE — dice cosa fare o non fare, non solo un concetto
2. Nomi ESATTI di funzioni/variabili/costanti
3. Anti-pattern in spec_hint: cosa succede se non si segue la regola
4. Una lesson = un concetto (non accorpare 3 cose)
5. Esempio codice inline dove utile (una o due righe)

ESEMPI DI FORMATO:
[
  {{
    "task_type": "interrupt",
    "lesson": "ISR BREVE: l'ISR deve solo settare flag o incrementare contatore. MAI Serial.print(), delay(), millis() dentro ISR. Lavoro reale nel loop() controllando il flag.",
    "spec_hint": "Serial.print() dentro ISR causa crash su ESP32 perché Serial usa interrupt interni",
    "hardware_quirk": null,
    "board": ""
  }},
  {{
    "task_type": "timer_nonbloccante",
    "lesson": "MILLIS OVERFLOW SAFE: usa 'now-lastTime>=INTERVAL'. MAI 'now>=lastTime+INTERVAL' — fallisce dopo 49 giorni quando millis() torna a 0.",
    "spec_hint": "lastTime+INTERVAL può overfloware diventando piccolo; unsigned subtraction gestisce overflow correttamente",
    "hardware_quirk": null,
    "board": ""
  }}
]

Genera tra 15 e 30 lessons. Priorità: bug frequenti non ovvi > differenze ESP32/AVR > pattern corretti.
Produci SOLO il JSON array. Inizia con [ e finisci con ]
"""

PROMPT_FROM_CODE = """\
Sei un esperto di programmazione Arduino/ESP32.

Analizza questo codice Arduino/ESP32 ed estrai lessons per una knowledge base di un agente AI.
Le lessons devono catturare pattern utili, anti-pattern, workaround hardware e best practices
presenti nel codice.

CODICE DA ANALIZZARE:
```cpp
{code}
```

FORMATO: Produci SOLO un array JSON valido, senza testo prima o dopo.
Ogni elemento:

  "task_type"     : categoria breve in snake_case
  "lesson"        : REGOLA CRITICA. Max 400 caratteri. Nomi esatti di funzioni/costanti.
  "spec_hint"     : anti-pattern o motivazione (può essere null)
  "hardware_quirk": nota hardware (può essere null)
  "board"         : "esp32:esp32:esp32" | "arduino:avr:uno" | ""

Estrai 5-20 lessons. Priorità:
- Pattern non ovvi o workaround hardware
- Configurazioni specifiche (pin, timing, indirizzi I2C)
- Errori comuni prevenuti dal codice

Produci SOLO il JSON array. Inizia con [ e finisci con ]
"""


# ── M40 client minimale ────────────────────────────────────────────────────────

def _ask_m40(prompt: str, max_tokens: int = 4096) -> str:
    import requests
    resp = requests.post(
        "http://localhost:11435/v1/chat/completions",
        json={
            "model": "qwen",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        },
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── Parse JSON dalla risposta ──────────────────────────────────────────────────

def _parse_lessons_json(text: str) -> list:
    """Estrae il primo array JSON valido dalla risposta di M40."""
    # Rimuovi eventuali markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()

    # Cerca [ ... ] anche se c'è testo attorno
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("Nessun array JSON trovato nella risposta")

    raw = text[start : end + 1]
    lessons = json.loads(raw)

    if not isinstance(lessons, list):
        raise ValueError("Il JSON non è un array")

    return lessons


# ── Importa in KB ─────────────────────────────────────────────────────────────

def _import_lessons(lessons: list, dry_run: bool = False) -> tuple[int, int]:
    ok = 0
    skip = 0
    for i, l in enumerate(lessons):
        task_type = l.get("task_type", "").strip()
        lesson    = l.get("lesson", "").strip()
        if not task_type or not lesson:
            print(f"  ⚠️  [{i}] campi vuoti — skipped")
            skip += 1
            continue
        if dry_run:
            print(f"  [DRY] [{task_type}] {lesson[:80]}...")
            ok += 1
            continue
        try:
            add_lesson(
                task_type=task_type,
                lesson=lesson,
                spec_hint=l.get("spec_hint"),
                hardware_quirk=l.get("hardware_quirk"),
                board=l.get("board", ""),
            )
            ok += 1
            print(f"  ✅  [{task_type}] {lesson[:80]}...")
        except Exception as e:
            print(f"  ❌  [{i}] {e}")
            skip += 1
    return ok, skip


# ── GitHub crawler ────────────────────────────────────────────────────────────

def _github_raw(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "agent-ino/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


def _list_github_repos(user: str) -> list[dict]:
    url = f"https://api.github.com/users/{user}/repos?per_page=100&type=public"
    data = json.loads(_github_raw(url))
    return [{"name": r["name"], "clone_url": r["clone_url"], "html_url": r["html_url"]}
            for r in data if not r.get("fork", False)]


def _list_ino_files(user: str, repo: str, branch: str = "main") -> list[str]:
    """Restituisce lista di URL raw di file .ino/.cpp nel repo."""
    urls = []
    for b in [branch, "master"]:
        try:
            tree_url = f"https://api.github.com/repos/{user}/{repo}/git/trees/{b}?recursive=1"
            tree = json.loads(_github_raw(tree_url))
            for item in tree.get("tree", []):
                if item["type"] == "blob" and item["path"].endswith((".ino", ".cpp")):
                    raw = f"https://raw.githubusercontent.com/{user}/{repo}/{b}/{item['path']}"
                    urls.append(raw)
            break
        except Exception:
            continue
    return urls


def crawl_github_user(user: str, dry_run: bool = False, max_files: int = 50):
    print(f"\n🔍  Crawl GitHub user: {user}")
    repos = _list_github_repos(user)
    print(f"  {len(repos)} repo pubblici trovati")

    total_ok = 0
    total_skip = 0
    files_done = 0

    for repo in repos:
        if files_done >= max_files:
            print(f"\n⚠️  Limite {max_files} file raggiunto — stop")
            break

        ino_files = _list_ino_files(user, repo["name"])
        if not ino_files:
            continue

        print(f"\n📁  {repo['name']} ({len(ino_files)} file .ino/.cpp)")

        for raw_url in ino_files:
            if files_done >= max_files:
                break
            try:
                code = _github_raw(raw_url)
                if len(code) < 100:
                    continue  # file vuoto o stub
                if len(code) > 12000:
                    code = code[:12000] + "\n// [troncato]"

                fname = raw_url.split("/")[-1]
                print(f"  📄  {fname} ({len(code)} chars) — chiedo M40...")

                prompt = PROMPT_FROM_CODE.format(code=code)
                raw_resp = _ask_m40(prompt, max_tokens=2048)
                lessons = _parse_lessons_json(raw_resp)

                print(f"      → {len(lessons)} lessons generate")
                ok, skip = _import_lessons(lessons, dry_run=dry_run)
                total_ok   += ok
                total_skip += skip
                files_done += 1
                time.sleep(1)  # pausa tra richieste

            except Exception as e:
                print(f"  ⚠️  {raw_url.split('/')[-1]}: {e}")

    return total_ok, total_skip


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera e importa lessons nella KB usando M40")
    parser.add_argument("topic", nargs="?", help="Argomento da analizzare (es: 'display TFT ST7735')")
    parser.add_argument("--dry-run", action="store_true", help="Mostra le lessons senza importarle")
    parser.add_argument("--from-code", metavar="FILE_OR_URL", help="Estrai lessons da file .ino o URL raw GitHub")
    parser.add_argument("--github-user", metavar="USER", help="Crawla tutti i repo pubblici di un utente GitHub")
    parser.add_argument("--save-json", metavar="FILE", help="Salva il JSON generato in un file")
    parser.add_argument("--max-files", type=int, default=50, help="Max file da crawlare per --github-user (default: 50)")
    args = parser.parse_args()

    if not any([args.topic, args.from_code, args.github_user]):
        parser.print_help()
        sys.exit(1)

    # ── Modalità crawl GitHub ──
    if args.github_user:
        ok, skip = crawl_github_user(args.github_user, dry_run=args.dry_run, max_files=args.max_files)
        print(f"\n{'─'*50}")
        print(f"TOTALE: {ok} importate, {skip} skipped")
        return

    # ── Modalità da codice ──
    if args.from_code:
        src = args.from_code
        if src.startswith("http"):
            print(f"📥  Download: {src}")
            code = _github_raw(src)
        else:
            code = Path(src).read_text(errors="replace")
        if len(code) > 12000:
            code = code[:12000] + "\n// [troncato]"
        prompt = PROMPT_FROM_CODE.format(code=code)
        label = Path(src).name if not src.startswith("http") else src.split("/")[-1]
    else:
        # ── Modalità topic ──
        prompt = PROMPT_TOPIC.format(topic=args.topic)
        label = args.topic

    print(f"\n{'─'*50}")
    print(f"📡  M40 — generazione lessons per: {label}")
    print(f"{'─'*50}")

    raw = _ask_m40(prompt, max_tokens=4096)

    try:
        lessons = _parse_lessons_json(raw)
    except Exception as e:
        print(f"\n❌  Parse JSON fallito: {e}")
        print("\n--- Risposta M40 grezza ---")
        print(raw[:2000])
        sys.exit(1)

    print(f"\n✅  {len(lessons)} lessons generate\n")

    if args.save_json:
        Path(args.save_json).write_text(json.dumps(lessons, indent=2, ensure_ascii=False))
        print(f"💾  JSON salvato in: {args.save_json}\n")

    ok, skip = _import_lessons(lessons, dry_run=args.dry_run)

    print(f"\n{'─'*50}")
    if args.dry_run:
        print(f"DRY RUN: {ok} lessons (non importate). Usa senza --dry-run per importare.")
    else:
        print(f"IMPORTATE: {ok}/{len(lessons)} | Skipped: {skip}")


if __name__ == "__main__":
    main()
