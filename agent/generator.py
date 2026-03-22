"""
Generator — usa M40 per generazione rapida di codice Arduino.
"""
import re
import sys

sys.path.insert(0, "/home/lele/codex-openai/programmatore_di_arduini")

from agent.m40_client import M40Client  # noqa: E402

SYSTEM_GLOBALS = """Sei un esperto programmatore Arduino.
Genera SOLO la sezione globals di uno sketch .ino:
- #include necessari
- #define e costanti
- Oggetti globali (es. Adafruit_SSD1306 display(...))
- Variabili globali

NON scrivere funzioni. Solo dichiarazioni.
Output: codice C++ puro, senza markdown, senza spiegazioni.
SEMPRE includi: Serial.begin() sarà in setup(), non qui.

REGOLA INCLUDE: includi SOLO le librerie necessarie per questo specifico task.
NON aggiungere librerie che non vengono usate. Nomi corretti (solo se usate):
- OLED SSD1306: #include <Adafruit_GFX.h> + #include <Adafruit_SSD1306.h>
- DHT sensore: #include <DHT.h>
- I2C: #include <Wire.h>
- OneWire/DS18B20: #include <OneWire.h> + #include <DallasTemperature.h>
- NeoPixel/FastLED: #include <FastLED.h>
- JSON: #include <ArduinoJson.h>
- Servo: #include <Servo.h>
- MQTT: #include <PubSubClient.h>

REGOLA I2C ESP32: SEMPRE Wire.begin(21, 22) con pin espliciti in setup().
NON usare Wire.begin() senza parametri — su alcuni ESP32 usa pin sbagliati.

REGOLA SSD1306: il costruttore Adafruit_SSD1306 ha 4 parametri: (W, H, &Wire, rst_pin).
Il 4° parametro è il pin di reset, NON l'indirizzo I2C. USA SEMPRE -1:
  Adafruit_SSD1306 display(128, 64, &Wire, -1);
L'indirizzo I2C (0x3C) va in display.begin(SSD1306_SWITCHCAPVCC, 0x3C).

REGOLA COLORI SSD1306: il display è MONOCROMATICO. Usa SOLO SSD1306_WHITE per disegnare.
NON usare mai: SSD1306_GREEN, SSD1306_RED, SSD1306_BLUE, ecc. — non esistono.
NON usare mai: Adafruit_GFX::WHITE — non è un membro di classe, è un #define, non funziona.
Corretto: display.drawRect(x, y, w, h, SSD1306_WHITE);
Sbagliato: display.drawRect(x, y, w, h, Adafruit_GFX::WHITE);

REGOLA TIMER millis(): SEMPRE dichiarare i timer come unsigned long, MAI come int.
Sbagliato: int lastSerialTime = 0;   ← overflow dopo 32 secondi → comportamento imprevedibile
Corretto: unsigned long lastSerialTime = 0;
Questo vale per: lastSerialTime, spawnTimer, prevMillis, lastMillis, ecc.

REGOLA dist(): La funzione dist(x1,y1,x2,y2) NON esiste in Arduino/ESP32.
Per calcolare distanza usare: sqrt(pow(x2-x1,2) + pow(y2-y1,2))
Oppure definire esplicitamente: float dist2d(float x1,float y1,float x2,float y2){return sqrt(pow(x2-x1,2)+pow(y2-y1,2));}
"""

SYSTEM_FUNCTION = """Sei un esperto programmatore Arduino.
Scrivi UNA SOLA funzione C++ completa per Arduino.
Output: SOLO il codice della funzione (firma + corpo), senza markdown, senza spiegazioni.
Includi la firma (es. "void setup() {") e la chiusura "}".
Il codice deve compilare senza errori.

REGOLE HARDWARE ESP32:
- Wire.begin(21, 22) — SEMPRE con pin espliciti, mai Wire.begin() senza args
- Adafruit_SSD1306 display(128, 64, &Wire, -1) — 4° param = rst_pin = -1
- display.begin(SSD1306_SWITCHCAPVCC, 0x3C) — indirizzo I2C qui, non nel costruttore
- SSD1306_WHITE — unico colore valido, mai SSD1306_GREEN/RED/BLUE

REGOLE CODICE:
- Ogni responsabilità in UNA SOLA funzione — mai duplicare logica tra funzioni
- loop() chiama ESATTAMENTE: updatePhysics(), updateDisplay() — nient'altro
- NON chiamare resolveCollisions() o drawBalls() direttamente in loop() — sono già dentro updatePhysics()/updateDisplay()
- Velocità iniziali: dopo random(), verifica sempre che vx!=0 e vy!=0 (if(vx==0) vx=1; if(vy==0) vy=1;)
- FISICA con delay(16): tratta vx/vy come pixel/frame, NON usare dt moltiplicatore. "x += vx" non "x += vx*dt".
  Velocità visibili su 128x64: vx/vy tra 1.5 e 3.0 px/frame. Con dt=0.016 e vx=3: movi 0.048px/frame = IMMOBILE.
  Alternativa: se vuoi usare dt, usa velocità in px/sec: vx tra 80 e 150 (es. random(80,150)).
- getTextBounds: display.getTextBounds(text, 0, 0, &x1, &y1, &tw, &th)
  Tipi: int16_t x1, y1; uint16_t tw, th;  — NON usare int per questi parametri
- NON esiste display.textWidth() — usare getTextBounds
- Le funzioni utente NON sono metodi di display — chiamarle senza "display."
- TIMER: unsigned long per variabili millis() — MAI int (overflow a 32s)
- dist(): NON esiste in Arduino — usare sqrt(pow(x2-x1,2)+pow(y2-y1,2))
- setupPhysics(): NON inventare funzioni inesistenti — metti init direttamente in setup()
- drawCircle(x,y,r,color): x,y,r DEVONO essere int — mai float direttamente: drawCircle((int)x,(int)y,(int)r,SSD1306_WHITE)
- BOIDS/PREDATORE: predator.id = indice preda TARGET (0..N-1). MAI predator.id = nextPreyId++ dopo init prede (porta OOB)
- BOIDS/RESPAWN: timer respawn per-preda (campo respawnTime in struct Boid), MAI timer globale lastRespawnTime condiviso
- BOIDS/RESPAWN: funzione respawnPrey(int i) con indice esplicito, MAI spawnPrey() con nextPreyId ciclico
- SERIAL: ogni messaggio multi-campo deve terminare con Serial.println(), mai Serial.print() — altrimenti messaggi si concatenano
- CONWAY/BIT-GRID: bit packing SEMPRE con colonna=x/8 e bit=x%8 — MAI x%BITMAP_COLS o x/BITMAP_COLS (produce coordinate errate)
  Usare helper: bool getCell(grid,x,y){return (grid[y][x/8]>>(x%8))&1;} void setCell(grid,x,y,v){if(v)grid[y][x/8]|=(1<<(x%8)); else grid[y][x/8]&=~(1<<(x%8));}
- CONWAY/SWAP: swapGrids() va chiamato UNA SOLA VOLTA per frame in loop() — computeNextGeneration() NON deve chiamarlo (altrimenti grid oscilla)
- CONWAY/SERIAL: timer millis() per Serial.print in loop() con variabile lastSerialTime, NON dentro printStatus() che fa return early senza aggiornare il timer
- CONWAY/COMPUTE: iterare su for(y) for(x) con x in 0..GRID_W, non su for(bitCol) for(x) — gridX = y*BITMAP_COLS+bitCol è SBAGLIATO
"""

SYSTEM_PROMPT = """Sei un esperto programmatore Arduino.
Quando generi codice:
- Produci SOLO codice Arduino valido (.ino)
- Includi tutti gli #include necessari
- Il codice deve compilare senza errori
- Aggiungi commenti brevi alle parti non ovvie
- Non aggiungere spiegazioni fuori dal codice a meno che non richieste
- SEMPRE inizializza Serial nella setup() con Serial.begin(115200)
- SEMPRE aggiungi Serial.println("READY"); come ultima riga di setup(), prima di qualsiasi loop

REGOLA INCLUDE: includi SOLO le librerie effettivamente usate nel codice.
NON aggiungere librerie non necessarie per il task corrente.
Nomi corretti (solo se la libreria è usata):
- OLED SSD1306: #include <Adafruit_GFX.h> + #include <Adafruit_SSD1306.h>
- DHT: #include <DHT.h>
- I2C: #include <Wire.h>
- OneWire/DS18B20: #include <OneWire.h> + #include <DallasTemperature.h>
- NeoPixel/FastLED: #include <FastLED.h>
- JSON: #include <ArduinoJson.h>
- Servo: #include <Servo.h>
- MQTT: #include <PubSubClient.h>

Per il debug visivo, includi nel codice segnali seriali VCAP:
- Serial.println("VCAP_READY"); — alla fine di setup(), quando il programma è pronto
- Serial.println("VCAP_START <N> <T>"); — per avviare cattura di N frame ogni T ms (usa i valori dal piano)
- Serial.println("VCAP_NOW <label>"); — per catturare un singolo frame su evento
Se il piano specifica vcap_frames=0, ometti i segnali VCAP.
"""

SYSTEM_PATCH = """Sei un esperto programmatore Arduino.
Correggi SOLO gli errori segnalati nel codice.

REGOLE FONDAMENTALI — RISPETTALE TUTTE:
- Correggi SOLO l'errore specifico indicato. Nient'altro.
- NON rimuovere funzioni, anche se sembrano incomplete o hanno solo commenti.
- NON semplificare funzioni in stub ("// Implement here", "// TODO", ecc.).
- NON aggiungere nuovi #include non presenti o non necessari.
- Mantieni TUTTI gli #include già presenti che non causano errori.
- Rimuovi SOLO i #include che causano errori "No such file or directory".
- Se l'errore è un backtick ` o ``` nel codice: rimuovi SOLO il backtick, nient'altro.
- Output: SOLO il codice corretto completo, senza markdown (NO ```, NO ```cpp), senza spiegazioni.
- CRITICO: il codice in output deve avere ALMENO tante righe quante ne ha il codice in input.
  Se il tuo output ha molte meno righe del codice originale, significa che hai eliminato funzioni — NON farlo.
- setup() e loop() DEVONO essere presenti nel codice in output. Se mancano, aggiungili.

REGOLA BACKTICK: se l'errore è "stray '`'" o "'cpp' does not name a type":
→ Rimuovi solo i caratteri ``` e ```cpp all'inizio/fine del codice.
→ NON modificare nessuna funzione, nessuna logica, nessun include.
→ Il corpo di ogni funzione deve rimanere IDENTICO all'originale.

REGOLA COLORI SSD1306: il display è MONOCROMATICO. Usa SOLO SSD1306_WHITE.
NON usare mai: SSD1306_GREEN, SSD1306_RED, SSD1306_BLUE, SSD1306_YELLOW, ecc.
NON usare mai: Adafruit_GFX::WHITE — causa "expected unqualified-id before numeric constant".
Usa SEMPRE: SSD1306_WHITE (o WHITE — è un alias definito dalla libreria).

ERRORE "expected unqualified-id before numeric constant" in Adafruit_SSD1306.h:74
→ Causa: macro #define con Adafruit_GFX::WHITE (o colori inesistenti SSD1306_GREEN ecc.)
→ Fix: sostituisci Adafruit_GFX::WHITE con SSD1306_WHITE e rimuovi #define di colori
"""


class Generator:
    def __init__(self):
        self.client = M40Client()

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def generate_code(
        self,
        task: str,
        context: str = "",
        board: str = "Arduino Uno",
        vcap_frames: int = 0,
        vcap_interval_ms: int = 1000,
    ) -> dict:
        """
        Genera uno sketch Arduino per il task dato.

        context         : snippet/docs rilevanti dal knowledge base
        vcap_frames     : quanti frame VCAP catturare (0 = nessuno)
        vcap_interval_ms: intervallo tra frame in ms
        ritorna: {"code": str, "thinking": str, "raw": str}
        """
        user_parts = [f"Board: {board}", f"Task: {task}"]
        if context:
            user_parts.append(f"\nContesto rilevante:\n{context}")
        if vcap_frames > 0:
            user_parts.append(
                f"\nDebug visivo richiesto: includi segnali VCAP. "
                f"vcap_frames={vcap_frames}, vcap_interval_ms={vcap_interval_ms}. "
                f"Usa VCAP_START {vcap_frames} {vcap_interval_ms} nel codice."
            )
        else:
            user_parts.append("\nDebug visivo non richiesto: ometti i segnali VCAP.")
        user_parts.append(
            "\nGenera il codice Arduino completo per il task."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

        result = self.client.generate(messages, max_tokens=4096, label="M40→Generator")
        code = self._extract_code(result["response"] or result["raw"])
        return {
            "code": code,
            "thinking": result["thinking"],
            "raw": result["raw"],
        }

    def generate_globals(self, nb, kb_example: str = "") -> dict:
        """
        Genera la sezione globals (#include, #define, variabili globali).
        kb_example: snippet funzionante dalla KB — usato come riferimento per include e costruttori.
        Ritorna: {"code": str, "thinking": str}
        """
        user_content = nb.context_for_globals()
        if kb_example:
            user_content += (
                "\n\nESEMPIO FUNZIONANTE DALLA KB (usa come riferimento per include e costruttori):\n"
                "```cpp\n" + kb_example[:800] + "\n```\n"
                "Adatta al task corrente mantenendo la stessa struttura di include e costruttori."
            )
        messages = [
            {"role": "system", "content": SYSTEM_GLOBALS},
            {"role": "user", "content": user_content},
        ]
        result = self.client.generate(messages, max_tokens=2048, label="M40→Globals")
        code = self._extract_code(result["response"] or result["raw"])
        return {"code": code, "thinking": result["thinking"]}

    def generate_function(self, nome: str, nb, kb_example: str = "") -> dict:
        """
        Genera una singola funzione Arduino.
        kb_example: snippet funzionante dalla KB — aiuta M40 a usare le API corrette.
        Ritorna: {"code": str, "thinking": str}
        """
        user_content = nb.context_for_function(nome)
        if kb_example:
            # Mostra solo le prime 400 chars dell'esempio — basta per le API
            user_content += (
                "\n\nRIFERIMENTO (API corrette da esempio funzionante):\n"
                "```cpp\n" + kb_example[:400] + "\n```"
            )
        messages = [
            {"role": "system", "content": SYSTEM_FUNCTION},
            {"role": "user", "content": user_content},
        ]
        result = self.client.generate(messages, max_tokens=2048, label=f"M40→{nome}()")
        code = self._extract_code(result["response"] or result["raw"])
        return {"code": code, "thinking": result["thinking"]}

    def patch_code(
        self,
        code: str,
        errors: list[dict],
        analysis: str = "",
        lessons: str = "",
    ) -> dict:
        """
        Corregge il codice dato gli errori del compilatore.

        errors: lista di {"line": int, "type": str, "message": str}
        analysis: spiegazione degli errori dall'orchestratore (opzionale)
        lessons: lezioni dalla KB rilevanti per gli errori (opzionale)
        ritorna: {"code": str, "thinking": str, "raw": str}
        """
        error_lines = []
        for e in errors:
            if isinstance(e, str):
                error_lines.append(f"  - {e}")
            else:
                line = e.get("line", "?")
                etype = e.get("type", "error")
                msg = e.get("message", "")
                error_lines.append(f"  - Riga {line} [{etype}]: {msg}")
        errors_text = "\n".join(error_lines) if error_lines else "  (nessun dettaglio)"

        user_content_parts = [
            "Il seguente codice Arduino non compila. Correggilo.",
            "",
            "=== CODICE ATTUALE ===",
            code,
            "",
            "=== ERRORI DI COMPILAZIONE ===",
            errors_text,
        ]
        if lessons:
            user_content_parts += ["", "=== LEZIONI DALLA KB (applica queste soluzioni) ===", lessons]
        if analysis:
            user_content_parts += ["", "=== ANALISI ===", analysis]

        user_content_parts += [
            "",
            "Riscrivi il codice corretto e funzionante.",
        ]

        messages = [
            {"role": "system", "content": SYSTEM_PATCH},
            {"role": "user", "content": "\n".join(user_content_parts)},
        ]

        result = self.client.generate(messages, max_tokens=4096, label="M40→Patcher")
        patched_code = self._extract_code(result["response"] or result["raw"])
        return {
            "code": patched_code,
            "thinking": result["thinking"],
            "raw": result["raw"],
        }

    # ------------------------------------------------------------------
    # Utility interna
    # ------------------------------------------------------------------

    def _extract_code(self, raw_response: str) -> str:
        """
        Estrae il codice Arduino dal testo del LLM.
        Rimuove: markdown fences, testo prima/dopo il codice.

        Regola 1 del progetto: il codice va ripulito prima di compilare.

        Strategia:
        1. Cerca blocchi ```cpp / ```arduino / ```c / ``` generico
        2. Se non trova fences, rimuove eventuali tag <think> e
           restituisce il testo rimanente
        """
        # Step 1 — rimuovi thinking se presente nel raw
        text = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()

        # Step 2 — cerca fence esplicita con linguaggio noto
        m = re.search(
            r"```(?:cpp|arduino|c\+\+|c)?\s*\n(.*?)```",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()

        # Step 3 — cerca qualsiasi fence generica ```
        m = re.search(r"```\n?(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()

        # Step 4 — fallback: restituisce tutto il testo ripulito
        return text.strip()
