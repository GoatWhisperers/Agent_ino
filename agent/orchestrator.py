"""
Orchestrator — usa MI50 per planning, analisi errori e valutazione.
"""
import json
import re
import sys

sys.path.insert(0, "/home/lele/codex-openai/programmatore_di_arduini")

from agent.mi50_client import MI50Client  # noqa: E402

_PLAN_SYSTEM = """Sei un architetto software esperto di Arduino e sistemi embedded.
Il tuo output deve essere ESCLUSIVAMENTE un oggetto JSON valido. Nessun testo prima o dopo.

STRUTTURA OBBLIGATORIA:
{
  "approach": "...",
  "libraries_needed": [],
  "key_points": [],
  "note_tecniche": [],
  "vcap_frames": 0,
  "vcap_interval_ms": 1000
}

Campi:
- approach: stringa, descrizione concisa dell'implementazione
- libraries_needed: array di stringhe, librerie Arduino necessarie (vuoto se nessuna)
- key_points: array di stringhe, passi implementativi in ordine (es. "setup I2C pin 21/22", "inizializza display")
- note_tecniche: array di stringhe, vincoli tecnici concreti (pin, indirizzi, baud rate, timing)
- vcap_frames: intero, frame webcam da catturare (0 = nessuno, >0 solo se LED/display/movimento visibile)
- vcap_interval_ms: intero, ms tra un frame e il successivo

ESEMPIO per "OLED SSD1306 mostra temperatura":
{"approach":"I2C su pin 21/22, SSD1306 addr 0x3C, Adafruit_SSD1306","libraries_needed":["Adafruit_SSD1306","Adafruit-GFX-Library"],"key_points":["Wire.begin(21,22) in setup","display.begin(SSD1306_SWITCHCAPVCC,0x3C)","display.clearDisplay() + display.println() + display.display()"],"note_tecniche":["SDA=GPIO21 SCL=GPIO22","I2C addr=0x3C","baud 115200"],"vcap_frames":3,"vcap_interval_ms":2000}

Rispondi SOLO con il JSON. Zero testo aggiuntivo.
"""

_PLAN_FUNCTIONS_SYSTEM = """Sei un architetto software esperto di Arduino e sistemi embedded.
Dato un task, produci il piano dettagliato delle FUNZIONI da implementare.
Output: ESCLUSIVAMENTE un oggetto JSON valido. Nessun testo prima o dopo.

STRUTTURA OBBLIGATORIA:
{
  "globals_hint": "stringa con suggerimento per #include, #define e variabili globali",
  "funzioni": [
    {
      "nome": "nomeC++",
      "firma": "tipoRitorno nomeC++(parametri)",
      "compito": "descrizione precisa di cosa fa questa funzione",
      "dipende_da": ["altrafunzione"]
    }
  ]
}

REGOLE:
- Includi SEMPRE setup() e loop() nella lista funzioni
- setup() non dipende da nulla (dipende_da: [])
- loop() dipende dalle funzioni helper che chiama
- Helper functions vanno prima di chi le usa in dipende_da
- globals_hint: elenca includes, defines, oggetti globali — per SSD1306 SEMPRE usare rst_pin=-1: "Adafruit_SSD1306 display(128,64,&Wire,-1)"
- NON scrivere codice nelle funzioni — solo la firma e il compito

ESEMPIO per "OLED mostra temperatura":
{
  "globals_hint": "#include <Wire.h>\n#include <Adafruit_GFX.h>\n#include <Adafruit_SSD1306.h>\n#define SCREEN_W 128\n#define SCREEN_H 64\nAdafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);  // -1 = no reset pin\nfloat lastTemp = 0;",
  "funzioni": [
    {"nome":"setup","firma":"void setup()","compito":"Wire.begin(21,22), Serial.begin(115200), display.begin(SSD1306_SWITCHCAPVCC,0x3C), display.clearDisplay()","dipende_da":[]},
    {"nome":"readTemperature","firma":"float readTemperature()","compito":"legge valore analogico da A0, converte con Steinhart-Hart, ritorna float gradi C","dipende_da":[]},
    {"nome":"showTemp","firma":"void showTemp(float temp)","compito":"display.clearDisplay(), stampa temp con 1 decimale e unità C, display.display()","dipende_da":[]},
    {"nome":"loop","firma":"void loop()","compito":"chiama readTemperature(), poi showTemp(), delay(1000), stampa su Serial","dipende_da":["readTemperature","showTemp"]}
  ]
}

Rispondi SOLO con il JSON. Zero testo aggiuntivo.
"""

_ANALYZE_ERRORS_SYSTEM = """Sei un esperto di compilazione C++ e Arduino/ESP32 con conoscenza profonda delle librerie Adafruit.
Il tuo output deve essere ESCLUSIVAMENTE un oggetto JSON valido. Nessun testo prima o dopo.

STRUTTURA OBBLIGATORIA:
{"analysis":"...","fix_hints":[]}

- analysis: stringa, causa degli errori spiegata chiaramente con la firma CORRETTA da usare
- fix_hints: array di stringhe, modifiche concrete e PRECISE da fare al codice

FIRME CORRETTE DA CONOSCERE (usale sempre quando pertinenti):
- getTextBounds: void getTextBounds(const char *str, int16_t x, int16_t y, int16_t *x1, int16_t *y1, uint16_t *w, uint16_t *h)
  Dichiarare: int16_t x1, y1; uint16_t tw, th;
  Chiamare:   display.getTextBounds(text, 0, 0, &x1, &y1, &tw, &th);
  Poi:        int px = (SCREEN_W - (int)tw) / 2;  int py = (SCREEN_H - (int)th) / 2;
- NON esiste display.textWidth() — usare sempre getTextBounds
- Le funzioni utente (es. drawTextCentrato()) sono AUTONOME, NON metodi di Adafruit_SSD1306 — chiamarle senza "display."
- display.begin(): display.begin(SSD1306_SWITCHCAPVCC, 0x3C)

Rispondi SOLO con il JSON. Zero testo aggiuntivo.
"""


def _safe_json(text: str, fallback: dict, required_keys: list[str] | None = None) -> dict:
    """
    Estrae e parsa il JSON dalla risposta del LLM.
    Strategia: prova in ordine e ritorna il primo successo.
      1. Blocco ```json ... ```
      2. Testo intero (se è già JSON puro)
      3. raw_decode da ogni '{' trovato (dal più tardi al più presto)
         — gestisce correttamente JSON con {} annidati nei valori stringa
    """
    # 1. blocco ```json
    m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # 2. testo intero
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # 3. raw_decode da ogni '{' trovato nel testo (dall'ultimo al primo)
    #    gestisce sia {"key": ...} che {\n  "key": ...} e {} annidati nei valori
    #    Se required_keys è specificato, salta i dict che non contengono tutte le chiavi attese
    decoder = json.JSONDecoder()
    pos = len(text)
    while True:
        pos = text.rfind("{", 0, pos)
        if pos < 0:
            break
        try:
            result, _ = decoder.raw_decode(text, pos)
            if isinstance(result, dict) and len(result) > 1:
                if required_keys is None or all(k in result for k in required_keys):
                    return result
        except (json.JSONDecodeError, ValueError):
            pass
        pos -= 1

    return fallback


class Orchestrator:
    def __init__(self):
        self.client = MI50Client.get()

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def plan_task(
        self,
        task: str,
        context: str = "",
        mode: str = "NEW",
    ) -> dict:
        """
        Dato un task, produce un piano di implementazione.

        ritorna: {
            "approach": str,
            "libraries_needed": list,
            "key_points": list,
            "thinking": str
        }
        """
        user_parts = [f"Modalità: {mode}", f"Task: {task}"]
        if context:
            user_parts.append(f"\nContesto:\n{context}")

        messages = [
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

        result = self.client.generate(messages, max_new_tokens=1024, label="MI50→Orchestrator")
        parsed = _safe_json(
            result["response"],
            fallback={
                "approach": result["response"],
                "libraries_needed": [],
                "key_points": [],
            },
            required_keys=["approach"],
        )
        return {
            "approach": parsed.get("approach", ""),
            "libraries_needed": parsed.get("libraries_needed", []),
            "key_points": parsed.get("key_points", []),
            "note_tecniche": parsed.get("note_tecniche", []),
            "vcap_frames": int(parsed.get("vcap_frames", 0)),
            "vcap_interval_ms": int(parsed.get("vcap_interval_ms", 1000)),
            "thinking": result["thinking"],
        }

    def plan_functions(self, task: str, context: str = "", mode: str = "NEW") -> dict:
        """
        Produce il piano dettagliato delle funzioni da implementare.

        Ritorna: {
            "globals_hint": str,
            "funzioni": [{"nome", "firma", "compito", "dipende_da"}],
            "thinking": str
        }
        """
        user_parts = [f"Modalità: {mode}", f"Task: {task}"]
        if context:
            user_parts.append(f"\nContesto:\n{context}")

        messages = [
            {"role": "system", "content": _PLAN_FUNCTIONS_SYSTEM},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

        result = self.client.generate(messages, max_new_tokens=1024, label="MI50→FuncPlanner")
        parsed = _safe_json(
            result["response"],
            fallback={"globals_hint": "", "funzioni": []},
            required_keys=["funzioni"],
        )
        return {
            "globals_hint": parsed.get("globals_hint", ""),
            "funzioni": parsed.get("funzioni", []),
            "thinking": result["thinking"],
        }

    def analyze_errors(self, code: str, errors: list[dict]) -> dict:
        """
        Analizza gli errori del compilatore e produce indicazioni per il fix.

        ritorna: {
            "analysis": str,
            "fix_hints": list[str],
            "thinking": str
        }
        """
        error_lines = []
        for e in errors:
            line = e.get("line", "?")
            etype = e.get("type", "error")
            msg = e.get("message", "")
            error_lines.append(f"  - Riga {line} [{etype}]: {msg}")
        errors_text = "\n".join(error_lines) if error_lines else "  (nessun dettaglio)"

        user_content = (
            "=== CODICE ===\n"
            + code
            + "\n\n=== ERRORI ===\n"
            + errors_text
        )

        messages = [
            {"role": "system", "content": _ANALYZE_ERRORS_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        result = self.client.generate(messages, max_new_tokens=1024, label="MI50→Orchestrator")
        parsed = _safe_json(
            result["response"],
            fallback={
                "analysis": result["response"],
                "fix_hints": [],
            },
            required_keys=["analysis"],
        )
        return {
            "analysis": parsed.get("analysis", ""),
            "fix_hints": parsed.get("fix_hints", []),
            "thinking": result["thinking"],
        }
