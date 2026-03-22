"""
Ingestion delle lessons estratte dai file lezione_*.md nella Knowledge Base.

Esegui con:
    source .venv/bin/activate
    python knowledge/ingest_docs.py

Aggiunge le lessons mancanti a SQLite + ChromaDB (via add_lesson → auto-sync).
Non duplica lessons già presenti (controlla per lesson text).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge.db import init_db, add_lesson
import sqlite3

DB_PATH = Path(__file__).parent / "arduino_agent.db"


def already_exists(lesson_text: str) -> bool:
    """Controlla se una lesson identica esiste già (match esatto prime 80 chars)."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT id FROM lessons WHERE lesson LIKE ?", (lesson_text[:80] + "%",))
    row = c.fetchone()
    conn.close()
    return row is not None


def add(task_type: str, lesson: str, spec_hint: str = "", hardware_quirk: str = ""):
    if already_exists(lesson):
        print(f"  [SKIP] già presente: {lesson[:60]}")
        return
    lid = add_lesson(
        task_type=task_type,
        lesson=lesson,
        spec_hint=spec_hint,
        hardware_quirk=hardware_quirk,
    )
    print(f"  [ADD ] {task_type}: {lesson[:70]}")
    return lid


# ─────────────────────────────────────────────────────────────────────────────
# LESSONS DA: lezione_predatore_v3.md, lezione_conway_v1.md, lezione_boids_completa.md
#             lezione_muretto2.md, lezione_attrattore.md
# ─────────────────────────────────────────────────────────────────────────────

LESSONS = [

    # ── Boids / Predatore ────────────────────────────────────────────────────

    ("boids_physics",
     "SEPARAZIONE: usare 1/d² (non 1/d) per forza di separazione — più stabile a corto raggio "
     "(Coulomb-like). Previene overlap senza perdere coesione a media distanza.",
     "sep_force = (1/d²) * inv_dir, poi normalizza e moltiplica per sep_weight", ""),

    ("boids_physics",
     "VELOCITÀ MINIMA: dopo ogni frame, se sqrt(vx²+vy²) < MIN_SPEED → rescala a MIN_SPEED. "
     "Previene stalli completi. if(vx==0)vx=1 non basta per velocità quasi-zero.",
     "Aggiungere: float spd=sqrt(vx*vx+vy*vy); if(spd<MIN_SPEED){float s=MIN_SPEED/spd; vx*=s; vy*=s;}", ""),

    ("boids_physics",
     "FORWARD DECLARATIONS: aggiungere dichiarazioni forward prima di setup() quando ci sono "
     "funzioni mutualmente ricorsive o definite dopo chi le chiama. Requisito C++.",
     "Aggiungere all'inizio: void updateBoids(); void drawBoids(); ecc.", ""),

    ("boids_physics",
     "DISTRIBUZIONE VELOCITÀ INIZIALE: random(150)/100.0 produce 0.0-1.5 (incl. zero). "
     "Usare 1.5+(float)random(100)/100.0 → garantisce 1.5-2.5 px/frame senza stalli.",
     "vx = 1.5 + (float)random(100)/100.0; if(random(2)) vx=-vx;", ""),

    ("boids_predator",
     "PREDATOR.ID: deve essere l'indice della preda TARGET (0..N-1), mai nextPreyId++ dopo "
     "l'inizializzazione delle prede — porta OOB (predator.id=8, prey[8] non esiste).",
     "Inizializzare predator.id = 0 (o findNearestPrey()) dopo aver creato tutte le prede", ""),

    ("boids_predator",
     "TIMER RESPAWN PER-PREDA: usare campo respawnTime in struct Boid, MAI lastRespawnTime "
     "globale condiviso. Il timer globale fa respawnare tutte le prede contemporaneamente.",
     "struct Boid { float x,y,vx,vy; bool alive; unsigned long respawnTime; };", ""),

    ("boids_predator",
     "RESPAWN PREDA: funzione respawnPrey(int i) con indice esplicito, MAI spawnPrey() con "
     "nextPreyId ciclico — porta a ID sempre crescente e RESPAWN:0 spam perché i==0 sempre.",
     "void respawnPrey(int i) { prey[i].x=random(W); prey[i].alive=true; prey[i].respawnTime=0; }", ""),

    # ── Serial ───────────────────────────────────────────────────────────────

    ("esp32_serial",
     "SERIAL NEWLINE: ogni messaggio seriale multi-campo DEVE terminare con Serial.println() "
     "non Serial.print(). Senza newline finale, HUNT e CATCH si concatenano sulla stessa riga.",
     "Usare: Serial.print('HUNT:'); Serial.print(id); ... Serial.println(); alla fine", ""),

    ("esp32_serial",
     "SERIAL SPAM REGEN: Serial.println('REGEN') chiamare UNA VOLTA in startRegen(), "
     "MAI dentro handleRegen() che viene chiamata ogni frame → 60 prints/secondo.",
     "startRegen(): set regenActive=true + Serial.println('REGEN'); handleRegen(): no serial", ""),

    # ── Collisioni ───────────────────────────────────────────────────────────

    ("collision_physics",
     "AABB MATTONCINO: NON fare doppio check vy<0 (una volta prima della chiamata, una dentro "
     "la funzione). La funzione gestisce internamente la direzione — chiamarla e basta.",
     "loop: if(checkBrickCollision(b, bricks[i])) {} — NON: if(vy<0 && checkBrick(...))", ""),

    ("collision_physics",
     "AABB OVERLAP: calcolare overlap su asse X e Y separatamente. Se overlapX < overlapY "
     "→ invertire vx, altrimenti invertire vy. NON usare solo vy<0 come heuristic.",
     "float ox=min(x+R,bx+W)-max(x-R,bx); float oy=...; if(ox<oy) vx=-vx; else vy=-vy;", ""),

    ("collision_physics",
     "AABB FORMULA CORRETTA: 4 check booleani separati: x+R>bx && x-R<bx+W && y+R>by && y-R<by+H. "
     "MAI usare abs(x-bx)<R+W (falsi positivi agli angoli).",
     "bool hit = (x+R>bx) && (x-R<bx+W) && (y+R>by) && (y-R<by+H);", ""),

    ("collision_physics",
     "RIMBALZO CON abs(): aggiornare posizione PRIMA del check bordi, poi usare abs() per "
     "garantire direzione uscente. if(x<R){x=R; vx=abs(vx);} — previene double-inversion.",
     "x += vx; if(x < R) { x = R; vx = abs(vx); } if(x > W-R) { x = W-R; vx = -abs(vx); }", ""),

    # ── Rigenerazione ────────────────────────────────────────────────────────

    ("game_logic",
     "REGEN FLAG: startRegen() deve settare esplicitamente regenActive=true. "
     "handleRegen() inizia con if(!regenActive) return; → senza il flag non fa nulla.",
     "void startRegen() { regenActive = true; regenIdx = 0; Serial.println('REGEN'); }", ""),

    ("game_logic",
     "FISHER-YATES SHUFFLE: inizializzare regenOrder[i]=i PRIMA dello shuffle. "
     "Array non inizializzato → shuffle su valori casuali → nessun mattoncino rigenera.",
     "for(int i=0;i<N;i++) regenOrder[i]=i; for(int i=N-1;i>0;i--){int j=random(i+1); swap...}", ""),

    # ── Attrattore/Fisica ────────────────────────────────────────────────────

    ("oled_physics",
     "FORZA ATTRATTORE: formula stabile: float d=sqrt(dx*dx+dy*dy); if(d>threshold) "
     "{vx+=(dx/d)*strength; vy+=(dy/d)*strength;} Strength ~0.06 su ESP32 128x64.",
     "Guard dist>threshold evita singolarità. Strength 0.04-0.08 visivamente fluido.", ""),

    ("oled_physics",
     "PATCHER M40 loop() deletion: dopo patch multi-round verificare che setup() e loop() "
     "esistano ancora. M40 può eliminare funzioni durante refactoring di errori complessi.",
     "Aggiungere al regression check: verifica presenza di 'void setup()' e 'void loop()'", ""),

    # ── Specification density ─────────────────────────────────────────────────

    ("task_specification",
     "SPECIFICHE PER FUNZIONE: dare pseudocodice funzione per funzione nel task description "
     "riduce i bug logici da 3-4 a 0 per run. M40 segue la spec, non inventa logica.",
     "Task: 'computeNext: for(y) for(x) vicini=countN(curr,x,y); applica regole Conway'", ""),

    ("task_specification",
     "INCLUDE LIST ESPLICITA: elencare i #include nel task description previene include "
     "sbagliati (SSD1306.h invece di Adafruit_SSD1306.h). M40 segue la lista.",
     "Task: 'Usa: #include<Wire.h> #include<Adafruit_GFX.h> #include<Adafruit_SSD1306.h>'", ""),

    # ── Math ─────────────────────────────────────────────────────────────────

    ("esp32_math",
     "MATH.H: includere <math.h> per cos/sin/sqrt su ESP32. Senza di esso alcune implementazioni "
     "non trovano sqrt() nonostante sia in stdlib. Necessario per boids/fisica.",
     "Aggiungere #include <math.h> quando usi sqrt, sin, cos, atan2", "ESP32 ESP-IDF"),

    # ── Conway ───────────────────────────────────────────────────────────────

    ("Conway",
     "STABILITY CHECK: usare getCell() helper per checkStability(), MAI confrontare "
     "direttamente con bit shift inline (grid[y][x/8]>>(7-(x%8))) vs (grid[y][x/8]>>(x%8)) "
     "— ordine bit inconsistente porta a stability=false sempre.",
     "bool same = getCell(curr,x,y)==getCell(next,x,y); return same per tutti x,y", ""),

    ("Conway",
     "NAMING CONFLICT: MAI usare stesso nome per variabile globale e funzione. "
     "'bool isStable=false' + 'bool isStable(){}' = errore C++ 'redeclared as different kind'. "
     "Usa: variabile 'isStableState', funzione 'checkStability()'.",
     "bool isStableState = false; ... bool checkStability(){...}", ""),

    ("Conway",
     "DISPLAY DRAWPIXEL: usare display.drawPixel(x, y, SSD1306_WHITE). "
     "display.setPixel() NON esiste su Adafruit_SSD1306 — errore di compilazione.",
     "display.drawPixel(x, y, SSD1306_WHITE) — unico metodo per singolo pixel", ""),

    # ── Resume / Sistema ──────────────────────────────────────────────────────

    ("system",
     "CHECKPOINT RESUME: il checkpoint sopravvive al crash del server. "
     "Leggere codegen_result, phase, step. Continuare dall'esatta posizione con --resume.",
     "python agent/tool_agent.py --resume logs/runs/<run_dir>/", ""),

    # ─────────────────────────────────────────────────────────────────────────
    # LESSONS DA: lezione_3palline.md, lezione_boids.md, lezione_conway_v2.md,
    #             lezione_conway_v3.md, lezione_muretto.md, lezione_occhio_bionico.md,
    #             lezione_predatore_completa.md, lezione_sistema_lessons.md
    # ─────────────────────────────────────────────────────────────────────────

    # ── 3 Palline / Fisica elastica ──────────────────────────────────────────

    ("collision_physics",
     "IMPULSO NEGATIVO: in collisione elastica verificare impulso < 0 prima di applicarlo. "
     "Impulso ≥ 0 significa sfere già in allontanamento — non applicare.",
     "if (impulso < 0) { vx1 += impulso*nx; vy1 += impulso*ny; }", ""),

    ("oled_physics",
     "DISPLAY UPDATE: clearDisplay() + disegno + display.display() — TUTTE E TRE necessarie ogni frame. "
     "Solo clearDisplay() senza display.display() → schermo nero.",
     "void draw() { display.clearDisplay(); drawPixel(...); display.display(); }", ""),

    ("collision_physics",
     "DISTANZA COLLISIONE: usare distSq <= (r1+r2)² — NON distSq <= r² (raggio singolo). "
     "Con 2 sfere di raggio 3: check (3+3)²=36, non 9.",
     "if (distSq <= (2*BALL_RADIUS)*(2*BALL_RADIUS)) { /* collisione */ }", ""),

    ("esp32_serial",
     "SERIAL COLLISIONE: stampare HIT solo quando avviene una collisione reale, non ogni N ms. "
     "Serial periodico senza evento mascherava fisica rotta in valutazione.",
     "if (collision_happened) Serial.println(\"HIT\");  // NON ogni 500ms", ""),

    # ── Boids puri ───────────────────────────────────────────────────────────

    ("boids_physics",
     "SEPARAZIONE THRESHOLD: applicare forza repulsiva SOLO se distanza < SEP_RADIUS (es. 8px). "
     "Senza threshold la forza esplode a corto raggio.",
     "if (dist < SEP_RADIUS) { repulsive force += 1/dist; }", ""),

    ("boids_physics",
     "ALLINEAMENTO AVERAGE: dividere la somma delle velocità per il numero di vicini. "
     "Somma senza divisione → forza cresce con il numero di vicini.",
     "if (cnt > 0) { dx /= cnt; dy /= cnt; }  // media, non somma", ""),

    ("oled_physics",
     "PESI FLOCKING: bilanciamento sep>ali>coh (es. 1.5:0.8:0.6) mantiene lo stormo coeso. "
     "Coesione troppo alta → implosione; separazione troppo alta → esplosione.",
     "steer = sep*1.5 + ali*0.8 + coh*0.6", ""),

    # ── Conway v2 ────────────────────────────────────────────────────────────

    ("Conway",
     "GETCELL/SETCELL: usare funzioni helper per bit packing: colonna=x/8, bit=x%8. "
     "MAI indexing diretto con x%BITMAP_COLS (bit order invertito).",
     "uint8_t getCell(uint8_t grid[][16], int x, int y) { return (grid[y][x/8] >> (x%8)) & 1; }", ""),

    ("Conway",
     "SERIAL TIMER IN LOOP: millis() check in loop(), NON dentro printStatus(). "
     "printStatus() in ogni frame → serial spam 8000 righe/sec.",
     "if (millis()-lastTime >= INTERVAL) { printStatus(); lastTime=millis(); }", ""),

    ("Conway",
     "SWAP GRIDS ONCE: swapGrids() chiamata UNA SOLA VOLTA per frame in loop(). "
     "computeNextGeneration() e checkStability() NON devono chiamare swap.",
     "In loop(): computeNext(); swapGrids(); checkStability(); draw();", ""),

    ("Conway",
     "COMPUTE ITERATE XY: computeNextGeneration() itera for(y) for(x) con getCell/setCell. "
     "MAI assumere rappresentazione packed nell'iterazione.",
     "for(y){for(x){ int n=countNeighbors(x,y); setCell(next,x,y,newState); }}", ""),

    ("oled_physics",
     "DELAY 16 IN LOOP: delay(16) dopo display.display() garantisce ~60fps E che millis() avanzi. "
     "Senza delay i timer millis()-based smettono di funzionare.",
     "delay(16); // dopo display.display() alla fine di loop()", ""),

    # ── Conway v3 ────────────────────────────────────────────────────────────

    ("Conway",
     "DRAWPIXEL API: display.drawPixel(x,y,color) è l'unico metodo per singolo pixel. "
     "display.setPixel() NON esiste su Adafruit_SSD1306 → errore compilazione.",
     "display.drawPixel(x, y, SSD1306_WHITE);", ""),

    ("Conway",
     "NAMING CONFLICT: MAI stesso nome per variabile globale e funzione. "
     "bool isStable=false + bool isStable(){} → 'redeclared as different kind of entity'.",
     "uint8_t isStableState; bool checkStability() { ... }", ""),

    # ── Muretto ──────────────────────────────────────────────────────────────

    ("collision_physics",
     "AABB MATTONCINO RISOLUZIONE: dopo check rect-circle, risolvere sovrapposizione spostando "
     "la palla fuori dal mattoncino prima di invertire la velocità.",
     "if (overlap) { reposiziona palla; if (sopra/sotto) vy=-vy; else vx=-vx; }", ""),

    ("game_logic",
     "RIGENERAZIONE CONTEGGIO: tracciare destroyed_count. Quando tutti i mattoncini sono distrutti "
     "riposizionarli e ripristinare hp. NON usare timer — usare contatore.",
     "if (destroyedCount == BRICK_COUNT) { for each brick: hp=MAX; randomPos(); }", ""),

    # ── Occhio Bionico / Evaluator ────────────────────────────────────────────

    ("evaluate_visual",
     "SERIAL FIRST: se expected_events trovati nel serial output → success=True immediato (0.1s). "
     "Il seriale è il verificatore funzionale più affidabile per fisica e eventi.",
     "if any(ev in serial for ev in expected_events): return True  # serial-first", ""),

    ("evaluate_visual",
     "BLOB STATISTICS: white_ratio da solo non basta. Usare blob_count + blob_avg_size. "
     "white_ratio > 15% può essere sfondo ambientale riflesso sull'OLED.",
     "if white_ratio>20% AND blob_count>3 AND blob_avg>5px: likely display active", ""),

    ("evaluate_visual",
     "M40 JUDGE TESTUALE: M40 VisualJudge su descrizione testuale (3s) è migliore di MI50-vision (5-10min). "
     "Mandare a M40: 'N blob piccoli, M blob medi' → M40 giudica vs task.",
     "Usare M40 VisualJudge per valutazione visiva rapida; MI50-vision solo come fallback", ""),

    ("evaluate_visual",
     "LIMITE PIXEL ANALYSIS: analisi pixel NON distingue fisica corretta da fisica rotta. "
     "Due animazioni identiche visivamente possono avere fisica opposta (vy invertito doppio).",
     "Affidarsi al serial (HIT/BREAK) per verificare la correttezza della fisica", ""),

    # ── Predatore Completo ───────────────────────────────────────────────────

    ("boids_predator",
     "SEEK TARGET UPDATE: il predatore deve aggiornare il target ogni frame — closest prey dinamico. "
     "Target fisso → predatore non cambia preda quando una viene catturata.",
     "closestPrey=0; for(j<N) if(dist(pred,j)<dist(pred,closestPrey)) closestPrey=j;", ""),

    ("boids_predator",
     "PREY FLEE RADIUS: la preda fugge SOLO se predatore è entro FLEE_RADIUS (es. 30px). "
     "Fuga costante senza radius check → tutte le prede sempre in fuga.",
     "if (dist_to_pred < FLEE_RADIUS) { flee_force = -direction * weight; }", ""),

    ("boids_predator",
     "BOUNCE NON WRAP: agenti fisici usano rimbalzo (abs velocity) NON wrap-around (teletrasporto). "
     "Wrap-around → predatore/preda sparisce e riappare → glitch visivo.",
     "if (x < 2) { x=2; vx=abs(vx); } if (x > 125) { x=125; vx=-abs(vx); }", ""),

    ("compiler_patcher",
     "M40 PATCHER REGRESSIONE: se codice patchato < 60% righe originale → M40 ha eliminato funzioni. "
     "Scartare il patch e tornare al codice originale.",
     "if len(patched) < 0.6*len(original): discard patch, use original", ""),

    # ── Sistema / Lessons ────────────────────────────────────────────────────

    ("system",
     "LESSONS SEMANTIC: lessons in KB recuperate per similarità al task (semantic search ChromaDB). "
     "Lessons task-type specifiche (OLED, physics, boids) → recupero corretto.",
     "search_lessons(task_desc, n=5) → top-5 lessons come contesto per MI50/M40", ""),

    ("system",
     "GUARD FASI: tool che modificano codice (plan_functions, generate_globals) bloccati in fasi avanzate. "
     "MI50 riceve cached result + hint 'chiama ADESSO: X' per avanzare.",
     "if phase >= COMPILING: return {skipped:True, reason:'...Chiama ADESSO: patch_code'}", ""),

]


def main():
    init_db()
    print(f"Ingesting {len(LESSONS)} lessons...")
    added = 0
    skipped = 0
    for entry in LESSONS:
        if len(entry) == 4:
            task_type, lesson, spec_hint, hardware_quirk = entry
        else:
            task_type, lesson = entry
            spec_hint = hardware_quirk = ""
        lid = add(task_type, lesson, spec_hint, hardware_quirk)
        if lid:
            added += 1
        else:
            skipped += 1
    print(f"\nDone: {added} aggiunte, {skipped} già presenti.")

    # Verifica conteggio finale
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM lessons")
    total = c.fetchone()[0]
    conn.close()
    print(f"Totale lessons in KB: {total}")


if __name__ == "__main__":
    main()
