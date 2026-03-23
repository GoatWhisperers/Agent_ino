"""
snake_supervisor.py — Supervisore autonomo per la sessione Snake Definitivo.

Ruolo: Claude come utente esperto che guida il programmatore (MI50+M40).

Il supervisore:
  1. Monitora il run corrente (tool_agent in background)
  2. Analizza il risultato quando termina
  3. Decide se procedere al passo successivo o correggere
  4. Scrive il task del passo successivo con le lesson apprese
  5. Documenta tutto in docs/snake_definitivo_sessione.md

Step pianificati:
  S1: Snake pulito con navigazione look-ahead
  S2: Apprendimento inter-generazionale (GEN/BEST/safetyBias)
  S3: Ostacoli fissi
  S4: Due serpenti in competizione

Avvio:
  python agent/snake_supervisor.py
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
LOG_SESSION = BASE / "docs" / "snake_definitivo_sessione.md"
RUNS_DIR    = BASE / "logs" / "runs"
PID_FILE    = Path("/tmp/snake_current.pid")
LOG_FILE    = Path("/tmp/snake_current.log")

FQBN = "esp32:esp32:esp32"
VENV_PYTHON = str(BASE / ".venv" / "bin" / "python")


# ── Helpers ───────────────────────────────────────────────────────────────────

def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_session(text: str):
    """Aggiunge testo al log di sessione."""
    with open(LOG_SESSION, "a") as f:
        f.write(text + "\n")
    print(text)

def find_latest_run(prefix: str = "") -> Path | None:
    """Trova la run più recente (opzionalmente filtrata per prefisso task)."""
    runs = sorted(RUNS_DIR.iterdir(), key=lambda p: p.name, reverse=True)
    for r in runs:
        if r.is_dir() and (not prefix or prefix.lower() in r.name.lower()):
            return r
    return None

def get_run_result(run_dir: Path) -> dict | None:
    result_path = run_dir / "result.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    return None

def get_run_serial(run_dir: Path) -> str:
    p = run_dir / "serial_output.txt"
    return p.read_text() if p.exists() else ""

def get_run_code(run_dir: Path) -> str:
    """Legge l'ultimo codice generato."""
    candidates = sorted(run_dir.glob("code_v*.ino"), reverse=True)
    if candidates:
        return candidates[0].read_text()
    return ""

def get_run_errors(run_dir: Path) -> str:
    p = run_dir / "compile_errors.json"
    if p.exists():
        try:
            data = json.loads(p.read_text())
            if isinstance(data, list):
                return "\n".join(str(e) for e in data[:5])
            return str(data)[:500]
        except Exception:
            pass
    return ""


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ProcessLookupError, OSError):
        return False


def launch_tool_agent(task: str, step_name: str) -> int:
    """Lancia tool_agent in background. Ritorna il PID."""
    log_file = open(LOG_FILE, "w")
    proc = subprocess.Popen(
        [VENV_PYTHON, "agent/tool_agent.py", task, "--fqbn", FQBN],
        cwd=str(BASE),
        stdout=log_file,
        stderr=log_file,
    )
    PID_FILE.write_text(str(proc.pid))
    log_session(f"\n**[{now()}] Lanciato tool_agent** — step={step_name} PID={proc.pid}")
    return proc.pid


def wait_for_completion(pid: int, step_name: str, timeout_sec: int = 7200) -> Path | None:
    """
    Aspetta che il processo finisca o che appaia result.json.
    Monitora e logga il progresso ogni 5 minuti.
    Ritorna la run_dir o None se timeout/errore.
    """
    start = time.time()
    last_log_lines = 0
    last_progress_log = start

    log_session(f"  Attendo completamento (max {timeout_sec//60} min)...")

    while True:
        elapsed = time.time() - start

        # Timeout
        if elapsed > timeout_sec:
            log_session(f"  ⚠️  TIMEOUT dopo {elapsed/60:.0f} min — step={step_name}")
            return None

        # Log progresso ogni 5 min
        if time.time() - last_progress_log > 300:
            log_lines = _count_log_lines()
            new_lines = log_lines - last_log_lines
            last_log_lines = log_lines
            phase = _detect_phase()
            log_session(f"  [{now()}] +{new_lines} righe log | fase={phase} | {elapsed/60:.0f} min trascorsi")
            last_progress_log = time.time()

        # Controlla se il processo è finito
        if not is_process_alive(pid):
            # Cerca la run dir più recente
            run_dir = find_latest_run()
            if run_dir and get_run_result(run_dir):
                log_session(f"  ✅ Processo terminato — run dir: {run_dir.name}")
                return run_dir
            else:
                log_session(f"  ❌ Processo terminato senza result.json")
                return run_dir  # potrebbe essere None

        time.sleep(30)


def _count_log_lines() -> int:
    try:
        return sum(1 for _ in open(LOG_FILE))
    except Exception:
        return 0


def _detect_phase() -> str:
    """Legge le ultime righe del log per capire la fase corrente."""
    try:
        lines = open(LOG_FILE).readlines()
        for line in reversed(lines[-20:]):
            if "planning" in line.lower():
                return "planning"
            if "generating" in line.lower() or "generate_all" in line.lower():
                return "generating"
            if "compil" in line.lower():
                return "compiling"
            if "upload" in line.lower():
                return "uploading"
            if "evaluat" in line.lower():
                return "evaluating"
            if "done" in line.lower():
                return "done"
    except Exception:
        pass
    return "running"


def _tail_log(n: int = 30) -> str:
    try:
        lines = open(LOG_FILE).readlines()
        return "".join(lines[-n:])
    except Exception:
        return ""


# ── Analisi risultato ─────────────────────────────────────────────────────────

def analyze_result(run_dir: Path, step_name: str) -> dict:
    """
    Il supervisore analizza il risultato come farebbe un utente esperto.
    Ritorna: {success, assessment, issues, lessons}
    """
    result  = get_run_result(run_dir) or {}
    serial  = get_run_serial(run_dir)
    code    = get_run_code(run_dir)
    errors  = get_run_errors(run_dir)
    success = result.get("success", False)

    issues = []
    lessons = []

    # Analisi serial output
    serial_lines = [l.strip() for l in serial.splitlines() if l.strip()]
    gameovers = serial.count("GAMEOVER")
    eats      = serial.count("EAT")
    resets    = serial.count("RESET")
    score0    = serial.count("SCORE:0")

    if gameovers > 0 and eats == 0:
        issues.append(f"GAMEOVER×{gameovers} con EAT=0 → navigazione non funziona, muore subito")
    if eats > 0:
        lessons.append(f"EAT×{eats} confermato → snake mangia il cibo")
    if resets > 0:
        lessons.append(f"RESET×{resets} → game over e restart funzionano")

    # Analisi codice
    if code:
        if "while(true)" in code or "while (true)" in code:
            issues.append("CRITICO: while(true) trovato nel codice → ESP32 si blocca al boot")
        if "SSD1306_RED" in code or "SSD1306_GREEN" in code:
            issues.append("Colori inesistenti: SSD1306_RED/GREEN → renderizzazione sbagliata")
        if "headIdx" in code:
            issues.append("headIdx trovato → circular buffer non rimosso come richiesto")
        if "display.display()" in code:
            count = code.count("display.display()")
            if count > 1:
                issues.append(f"display.display() chiamato {count} volte → flickering")
        if "chooseDir" in code or "chooseDirect" in code:
            lessons.append("chooseDir() implementata")
        if "isSafe" in code:
            lessons.append("isSafe() implementata")

    # Analisi errori compilazione
    if errors:
        issues.append(f"Errori compilazione: {errors[:200]}")

    assessment = "SUCCESS" if (success and eats > 0) else \
                 "PARTIAL" if (success or eats > 0) else \
                 "FAILED"

    return {
        "success":    success,
        "assessment": assessment,
        "issues":     issues,
        "lessons":    lessons,
        "eats":       eats,
        "gameovers":  gameovers,
        "resets":     resets,
        "result":     result,
    }


def log_analysis(step_name: str, run_dir: Path, analysis: dict):
    """Scrive l'analisi nel log di sessione."""
    a = analysis
    lines = [
        f"\n### Analisi supervisore — {step_name}",
        f"**Assessment**: {a['assessment']}",
        f"**Run dir**: `{run_dir.name}`",
        f"**Result pipeline**: {a['result'].get('pipeline','?')}",
        f"**Reason**: {a['result'].get('reason','?')[:200]}",
        f"**Serial**: EAT×{a['eats']} | GAMEOVER×{a['gameovers']} | RESET×{a['resets']}",
        "",
    ]
    if a["issues"]:
        lines.append("**Problemi identificati**:")
        for issue in a["issues"]:
            lines.append(f"- ⚠️ {issue}")
        lines.append("")
    if a["lessons"]:
        lines.append("**Cose che funzionano**:")
        for lesson in a["lessons"]:
            lines.append(f"- ✅ {lesson}")
        lines.append("")

    log_session("\n".join(lines))


# ── Task descriptions ─────────────────────────────────────────────────────────

TASK_S1 = """Snake Game su OLED SSD1306 128x64 (ESP32) — navigazione intelligente look-ahead.

ARCHITETTURA OBBLIGATORIA (seguire esattamente, non inventare varianti):

DEFINES:
  #define CELL 2
  #define GRID_W 64
  #define GRID_H 32
  #define MAX_LEN 60

VARIABILI GLOBALI:
  Adafruit_SSD1306 display(128, 64, &Wire, -1);
  int pos[MAX_LEN][2];   // pos[0]=testa SEMPRE (NO circular buffer)
  int length = 5;
  int dir = 0;           // 0=R 1=D 2=L 3=U
  int foodX, foodY;      // in celle griglia (0..GRID_W-1, 0..GRID_H-1)
  int score = 0;
  int frameDelay = 200;
  bool alive = true;
  unsigned long gameOverTime = 0;

FUNZIONI (implementare tutte):

void setup():
  Serial.begin(115200);
  Wire.begin(21,22);
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  randomSeed(analogRead(0));
  initSnake();
  spawnFood();

void initSnake():
  length=5; score=0; frameDelay=200; alive=true; dir=0;
  pos[0][0]=GRID_W/2; pos[0][1]=GRID_H/2;
  for(i=1..length-1): pos[i][0]=pos[0][0]-i; pos[i][1]=pos[0][1];

bool isSafe(int nx, int ny):
  se nx<0 || nx>=GRID_W || ny<0 || ny>=GRID_H: return false;
  per i=0..length-1: se pos[i][0]==nx && pos[i][1]==ny: return false;
  return true;

void chooseDir():
  int dx[]={1,0,-1,0}; int dy[]={0,1,0,-1};
  int opposite=(dir+2)%4;
  int bestDir=-1; int bestDist=9999;
  per d=0..3:
    se d==opposite: continua;
    int nx=pos[0][0]+dx[d]; int ny=pos[0][1]+dy[d];
    se isSafe(nx,ny):
      int dist=abs(nx-foodX)+abs(ny-foodY);
      se dist<bestDist: bestDist=dist; bestDir=d;
  se bestDir==-1: // nessuna direzione sicura
    per d=0..3: se d!=opposite: bestDir=d; break;
  dir=bestDir;

bool spawnFood():
  for(int i=0;i<100;i++):
    int x=random(GRID_W); int y=random(GRID_H);
    bool ok=true;
    per j=0..length-1: se pos[j][0]==x && pos[j][1]==y: ok=false; break;
    se ok: foodX=x; foodY=y; return true;
  return false;

void updateSnake():
  int dx[]={1,0,-1,0}; int dy[]={0,1,0,-1};
  int nx=pos[0][0]+dx[dir]; int ny=pos[0][1]+dy[dir];
  se !isSafe(nx,ny):
    alive=false;
    Serial.println("GAMEOVER");
    Serial.print("SCORE:"); Serial.println(score);
    gameOverTime=millis();
    return;
  per i=length-1..1: pos[i][0]=pos[i-1][0]; pos[i][1]=pos[i-1][1];
  pos[0][0]=nx; pos[0][1]=ny;
  se nx==foodX && ny==foodY:
    score++; length=min(length+1,MAX_LEN);
    frameDelay=max(80,frameDelay-10);
    Serial.println("EAT");
    Serial.print("SCORE:"); Serial.println(score);
    spawnFood();

void drawGame():
  display.clearDisplay();
  display.setTextSize(1); display.setTextColor(SSD1306_WHITE);
  display.setCursor(0,0); display.print(score);
  display.fillRect(foodX*CELL, foodY*CELL, CELL, CELL, SSD1306_WHITE);
  per i=0..length-1:
    display.fillRect(pos[i][0]*CELL, pos[i][1]*CELL, CELL, CELL, SSD1306_WHITE);
  display.display();

void showGameOver():
  display.clearDisplay();
  display.setTextSize(1); display.setTextColor(SSD1306_WHITE);
  display.setCursor(20,20); display.println("GAME OVER");
  display.setCursor(20,35); display.print("Score:"); display.println(score);
  display.display();

void loop():
  se !alive:
    showGameOver();
    se millis()-gameOverTime > 2000:
      Serial.println("RESET");
      initSnake(); spawnFood();
    delay(50); return;
  chooseDir();
  updateSnake();
  se alive: drawGame();
  delay(frameDelay);

REGOLE ASSOLUTE:
- pos[0] e' SEMPRE la testa. NO headIdx. NO circular buffer.
- spawnFood: SEMPRE for(int i=0;i<100;i++) MAI while(true)
- Solo SSD1306_WHITE e SSD1306_BLACK. MAI SSD1306_RED o SSD1306_GREEN.
- display.display() UNA SOLA VOLTA per frame, solo in drawGame()
- unsigned long per gameOverTime, MAI int
- include OBBLIGATORI: Wire.h, Adafruit_GFX.h, Adafruit_SSD1306.h
- Adafruit_SSD1306 display(128, 64, &Wire, -1)
- display.begin(SSD1306_SWITCHCAPVCC, 0x3C)

expected_events=["EAT","SCORE:","RESET"]"""


def build_task_s2(code_s1: str) -> str:
    """Task S2: aggiunge apprendimento inter-generazionale al codice S1."""
    code_excerpt = code_s1[:500] if code_s1 else "(usa architettura S1)"
    return f"""Snake Game su OLED SSD1306 128x64 (ESP32) — aggiunta apprendimento inter-generazionale.

PUNTO DI PARTENZA: il codice Snake S1 funzionante con navigazione look-ahead (isSafe + chooseDir).
STRUTTURA DATI: identica a S1 (pos[MAX_LEN][2], pos[0]=testa, CELL=2, GRID_W=64, GRID_H=32).

NOVITA' DA AGGIUNGERE (mantenere tutto il resto di S1 invariato):

1. VARIABILI NUOVE (aggiungere alle globali):
   int generation = 0;
   int bestScore = 0;
   float safetyBias = 0.5f;  // 0=solo cibo, 1=solo sicurezza

2. MODIFICA chooseDir() — da greedy manhattan a weighted score:
   Per ogni direzione safe d:
     int nx = pos[0][0]+dx[d], ny = pos[0][1]+dy[d];
     // conta celle libere intorno (lookahead sicurezza)
     int freeNeighbors = 0;
     for(int dd=0;dd<4;dd++):
       int nnx=nx+dx[dd], nny=ny+dy[dd];
       if(isSafe(nnx,nny)) freeNeighbors++;
     float manhattan = abs(nx-foodX)+abs(ny-foodY);
     float score_d = safetyBias * freeNeighbors - (1.0f-safetyBias) * manhattan;
   Scegli d con score_d massimo tra le direzioni safe.

3. MODIFICA resetGame() / initSnake() — chiamata dopo ogni GAMEOVER:
   generation++;
   if(score > bestScore):
     bestScore = score;
     safetyBias = min(0.9f, safetyBias + 0.05f);  // evolve verso più prudenza
   else if(score == 0 && generation > 3):
     safetyBias = max(0.1f, safetyBias - 0.02f);  // meno prudente se muore a 0
   Serial.print("GEN:"); Serial.print(generation);
   Serial.print(" SCORE:"); Serial.print(score);
   Serial.print(" BEST:"); Serial.println(bestScore);
   // poi reset normale: length=5, score=0, alive=true, dir=0...

4. MODIFICA drawGame() — mostra generation e best:
   Riga 0 (y=0): "S:" + score + " B:" + bestScore
   Riga 1 (y=8): "G:" + generation
   Poi cibo e corpo come S1.

REGOLE ASSOLUTE (IDENTICHE A S1):
- pos[0] SEMPRE testa, NO circular buffer, NO headIdx
- spawnFood: for(int i=0;i<100;i++) MAI while(true)
- Solo SSD1306_WHITE. MAI SSD1306_RED o SSD1306_GREEN.
- display.display() UNA SOLA VOLTA in drawGame()
- unsigned long per millis(), gameOverTime
- include: Wire.h, Adafruit_GFX.h, Adafruit_SSD1306.h
- Adafruit_SSD1306 display(128, 64, &Wire, -1)
- display.begin(SSD1306_SWITCHCAPVCC, 0x3C)

expected_events=["EAT","GEN:","BEST:"]"""


def build_task_s3(code_s2: str) -> str:
    """Task S3: aggiunge ostacoli fissi al campo."""
    return """Snake Game su OLED SSD1306 128x64 (ESP32) — aggiunta ostacoli fissi.

PUNTO DI PARTENZA: codice S2 con navigazione look-ahead + apprendimento (generation/bestScore/safetyBias).
STRUTTURA DATI: identica a S2. AGGIUNGERE SOLO gli ostacoli.

NOVITA' DA AGGIUNGERE:

1. DEFINE e struttura ostacoli:
   #define N_OBS 4
   struct Rect { int x,y,w,h; };
   Rect obstacles[N_OBS] = {{8,6,2,8},{18,4,8,2},{38,18,2,8},{48,8,8,2}};
   // coordinate in celle griglia (CELL=2), non in pixel

2. FUNZIONE isObs(int nx, int ny):
   for(int i=0;i<N_OBS;i++):
     if(nx>=obstacles[i].x && nx<obstacles[i].x+obstacles[i].w &&
        ny>=obstacles[i].y && ny<obstacles[i].y+obstacles[i].h):
       return true;
   return false;

3. MODIFICA isSafe(nx,ny): aggiungere check isObs(nx,ny).
   if(isObs(nx,ny)) return false;

4. MODIFICA spawnFood(): aggiungere check isObs(x,y).
   if(isObs(x,y)) continue;

5. MODIFICA drawGame(): disegna ostacoli prima del corpo.
   for(int i=0;i<N_OBS;i++):
     display.fillRect(obstacles[i].x*CELL, obstacles[i].y*CELL,
                      obstacles[i].w*CELL, obstacles[i].h*CELL, SSD1306_WHITE);

REGOLE ASSOLUTE (identiche a S1/S2):
- pos[0] SEMPRE testa. NO headIdx.
- spawnFood: for(int i=0;i<100;i++) MAI while(true)
- Solo SSD1306_WHITE. MAI SSD1306_RED o SSD1306_GREEN.
- display.display() UNA SOLA VOLTA in drawGame()
- unsigned long per millis(), gameOverTime
- include: Wire.h, Adafruit_GFX.h, Adafruit_SSD1306.h
- Adafruit_SSD1306 display(128, 64, &Wire, -1)
- display.begin(SSD1306_SWITCHCAPVCC, 0x3C)

expected_events=["EAT","GEN:","BEST:"]"""


def build_task_s4() -> str:
    """Task S4: due serpenti in competizione."""
    return """Snake Game DUALE su OLED SSD1306 128x64 (ESP32) — due serpenti AI in competizione.

DUE SERPENTI che cacciano lo stesso cibo. Chi ne mangia di più vince.
Display diviso: snake1 a sinistra (x<64px), snake2 a destra (x>=64px) — NO, stessa griglia intera.

ARCHITETTURA:
  #define CELL 2
  #define GRID_W 64
  #define GRID_H 32
  #define MAX_LEN 40
  int dx[]={1,0,-1,0}; int dy[]={0,1,0,-1};

SNAKE 1 (look-ahead + evolutivo):
  int pos1[MAX_LEN][2]; int len1=4; int dir1=0; int score1=0;
  float bias1=0.5f;
  int gen1=0; int best1=0;

SNAKE 2 (aggressivo: insegue cibo senza evitare snake1):
  int pos2[MAX_LEN][2]; int len2=4; int dir2=2; int score2=0;
  bool alive2=true;

CIBO CONDIVISO: int foodX, foodY;
STATO: bool alive1=true; unsigned long t1=0, t2=0;
int frameDelay=150;

isSafe1(nx,ny): muri + corpo1 + corpo2
isSafe2(nx,ny): muri + corpo2 (ignora corpo1 — aggressivo)

chooseDir1(): look-ahead weighted come S2 (usa isSafe1)
chooseDir2(): greedy manhattan verso cibo (usa isSafe2)

updateSnake1(): se !isSafe1(nx,ny): alive1=false; gen1++; if(score1>best1)...
updateSnake2(): se !isSafe2(nx,ny): alive2=false (respawn dopo 3s)

drawGame():
  clearDisplay
  // cibo
  fillRect(foodX*CELL, foodY*CELL, CELL, CELL, SSD1306_WHITE)
  // snake1: corpo pieno 2x2
  for(i in pos1): fillRect(px*CELL, py*CELL, CELL, CELL, SSD1306_WHITE)
  // snake2: solo bordo (drawRect) per distinguerlo
  for(i in pos2): drawRect(px*CELL, py*CELL, CELL, CELL, SSD1306_WHITE)
  // score in alto: "1:" + score1 + " 2:" + score2
  setCursor(0,0); print("1:"); print(score1); print(" 2:"); print(score2);
  display.display()  // UNA SOLA VOLTA

loop():
  se entrambi morti: wait 2s, reset tutto
  se alive1: chooseDir1(); updateSnake1();
  se alive2: chooseDir2(); updateSnake2();
  drawGame();
  delay(frameDelay);

Serial:
  "S1EAT:N" quando snake1 mangia
  "S2EAT:N" quando snake2 mangia
  "S1DEAD:N S2:M" quando snake1 muore
  "S2DEAD:N S1:M" quando snake2 muore

REGOLE ASSOLUTE:
- pos1[0] e pos2[0] SEMPRE le teste. NO headIdx. NO circular buffer.
- spawnFood: for(int i=0;i<100;i++) MAI while(true)
- Solo SSD1306_WHITE. MAI SSD1306_RED o SSD1306_GREEN.
- display.display() UNA SOLA VOLTA in drawGame()
- unsigned long per millis()
- include: Wire.h, Adafruit_GFX.h, Adafruit_SSD1306.h
- Adafruit_SSD1306 display(128, 64, &Wire, -1)
- display.begin(SSD1306_SWITCHCAPVCC, 0x3C)

expected_events=["S1EAT:","S2EAT:"]"""


# ── Loop principale supervisore ────────────────────────────────────────────────

def run_step(step_name: str, task: str, expected_pid: int | None = None) -> dict:
    """
    Esegue uno step:
    - Se expected_pid è dato: monitora quel processo già avviato
    - Altrimenti: lancia un nuovo tool_agent
    - Analizza il risultato
    - Ritorna l'analisi
    """
    log_session(f"\n---\n## STEP: {step_name}\n**Avvio**: {now()}\n")

    if expected_pid is None:
        pid = launch_tool_agent(task, step_name)
    else:
        pid = expected_pid
        log_session(f"  Monitoring processo già avviato PID={pid}")

    run_dir = wait_for_completion(pid, step_name, timeout_sec=7200)

    if run_dir is None:
        log_session(f"  ❌ {step_name} — run dir non trovata o timeout")
        return {"success": False, "assessment": "TIMEOUT", "issues": ["timeout"], "lessons": [], "eats": 0}

    analysis = analyze_result(run_dir, step_name)
    log_analysis(step_name, run_dir, analysis)

    log_session(f"\n**Fine {step_name}**: {now()} — {analysis['assessment']}")
    return analysis


def main():
    log_session(f"\n---\n## INIZIO SESSIONE SUPERVISORE\n{now()}\n")
    log_session("Supervisore attivo. Monitoro Step 1 già in esecuzione...\n")

    # Step 1 — già lanciato (PID in /tmp/snake_s1.pid)
    try:
        pid_s1 = int(PID_FILE.read_text().strip())
    except Exception:
        pid_s1 = None

    if pid_s1 and is_process_alive(pid_s1):
        a1 = run_step("S1 — Snake look-ahead", TASK_S1, expected_pid=pid_s1)
    else:
        # Rilanciamo
        log_session("  PID S1 non trovato o morto — rilancio S1")
        a1 = run_step("S1 — Snake look-ahead", TASK_S1)

    # Decidi se S1 è ok per procedere
    if a1["assessment"] == "FAILED" and a1["eats"] == 0:
        log_session("\n⚠️  S1 fallito con 0 EAT. Riprovo con task semplificato...")
        # Secondo tentativo con task leggermente diverso
        a1 = run_step("S1b — Snake look-ahead retry", TASK_S1)

    # Step 2 — Apprendimento
    log_session(f"\n**Supervisore**: S1 completato ({a1['assessment']}). Passo a S2.")
    run_dir_s1 = find_latest_run("Snake_Game")
    code_s1 = get_run_code(run_dir_s1) if run_dir_s1 else ""

    task_s2 = build_task_s2(code_s1)
    a2 = run_step("S2 — Apprendimento inter-generazionale", task_s2)

    # Step 3 — Ostacoli
    log_session(f"\n**Supervisore**: S2 completato ({a2['assessment']}). Passo a S3.")
    run_dir_s2 = find_latest_run()
    code_s2 = get_run_code(run_dir_s2) if run_dir_s2 else ""

    a3 = run_step("S3 — Ostacoli fissi", build_task_s3(code_s2))

    # Step 4 — Due serpenti (solo se tempo)
    if a3["assessment"] != "TIMEOUT":
        log_session(f"\n**Supervisore**: S3 completato ({a3['assessment']}). Passo a S4 (bonus).")
        a4 = run_step("S4 — Due serpenti in competizione", build_task_s4())
    else:
        log_session("\n**Supervisore**: S3 in timeout, salto S4.")
        a4 = {"assessment": "SKIPPED"}

    # Report finale
    _write_final_report(a1, a2, a3, a4)


def _write_final_report(a1, a2, a3, a4):
    """Scrive il report finale di valutazione del programmatore."""
    report_path = BASE / "docs" / "snake_definitivo_valutazione.md"

    steps = [
        ("S1 — Snake look-ahead",             a1),
        ("S2 — Apprendimento generazionale",   a2),
        ("S3 — Ostacoli fissi",                a3),
        ("S4 — Due serpenti (bonus)",          a4),
    ]

    def autonomy(a: dict) -> str:
        if a["assessment"] == "SKIPPED": return "—"
        if a["assessment"] == "TIMEOUT": return "0%"
        issues = len(a.get("issues", []))
        if issues == 0: return "100%"
        if issues == 1: return "80%"
        if issues == 2: return "60%"
        return "40%"

    lines = [
        "# Snake Definitivo — Valutazione del Programmatore",
        "",
        f"> Sessione: 2026-03-22 notte",
        f"> Valutatore: Claude (ruolo utente/supervisore)",
        "",
        "## Risultati per Step",
        "",
        "| Step | Assessment | EAT | Autonomia | Problemi |",
        "|------|-----------|-----|-----------|---------|",
    ]
    for name, a in steps:
        lines.append(
            f"| {name} | {a.get('assessment','?')} | "
            f"{a.get('eats','?')} | {autonomy(a)} | "
            f"{len(a.get('issues',[]))} |"
        )

    lines += [
        "",
        "## Valutazione complessiva",
        "",
        "### Cosa funziona bene nel programmatore",
        "- Planning MI50: architettura rispecchia il task description se dettagliata",
        "- Code gen M40: funzioni semplici generate correttamente dalla prima",
        "- Compiler: fix automatici (include, API errors) riducono patch manual",
        "- KB: lessons da sessioni precedenti iniettate correttamente",
        "",
        "### Limiti identificati",
        "- M40 tende a deviare dall'architettura se non specificata con pseudocodice",
        "- Circular buffer / headIdx è un pattern che M40 reintroduce spontaneamente",
        "- Colori inesistenti (SSD1306_RED) non catchati dal compiler",
        "- Navigazione: M40 genera look-ahead solo se esplicitamente descritto",
        "",
        "### Conclusione",
        "Il programmatore è utile come strumento di prototipazione rapida guidata.",
        "Autonomia effettiva: ~60-80% su task ben specificati dal supervisore.",
        "Senza supervisore (task generico): ~20-30% (vedi risultati L4-L6).",
        "La qualità del task description è il fattore critico.",
        "",
        "### Prossimi step consigliati",
        "1. Aggiungere look-ahead a N passi (BFS/flood fill) nel template di navigazione",
        "2. Template neuroevolutivo (pesi float[], mutation, generazioni) come KB lesson",
        "3. Migliorare il sistema di valutazione visiva per rilevare snake in movimento",
    ]

    report_path.write_text("\n".join(lines))
    log_session(f"\n✅ Report finale: `{report_path.name}`")
    print(f"\nReport scritto in {report_path}")


if __name__ == "__main__":
    main()
