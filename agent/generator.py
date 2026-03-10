"""
Generator — usa M40 per generazione rapida di codice Arduino.
"""
import re
import sys

sys.path.insert(0, "/home/lele/codex-openai/programmatore_di_arduini")

from agent.m40_client import M40Client  # noqa: E402

SYSTEM_GLOBALS = """/no_think
Sei un esperto programmatore Arduino.
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

REGOLA SSD1306: il costruttore Adafruit_SSD1306 ha 4 parametri: (W, H, &Wire, rst_pin).
Il 4° parametro è il pin di reset, NON l'indirizzo I2C. USA SEMPRE -1:
  Adafruit_SSD1306 display(128, 64, &Wire, -1);
L'indirizzo I2C (0x3C) va in display.begin(SSD1306_SWITCHCAPVCC, 0x3C).
"""

SYSTEM_FUNCTION = """/no_think
Sei un esperto programmatore Arduino.
Scrivi UNA SOLA funzione C++ completa per Arduino.
Output: SOLO il codice della funzione (firma + corpo), senza markdown, senza spiegazioni.
Includi la firma (es. "void setup() {") e la chiusura "}".
Il codice deve compilare senza errori.
"""

SYSTEM_PROMPT = """/no_think
Sei un esperto programmatore Arduino.
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

SYSTEM_PATCH = """/no_think
Sei un esperto programmatore Arduino.
Correggi SOLO gli errori segnalati nel codice.

REGOLE FONDAMENTALI:
- NON aggiungere nuovi #include che non erano già presenti o non sono strettamente necessari
- NON rimuovere funzionalità esistenti
- Mantieni tutti gli #include già presenti che non causano errori
- Rimuovi SOLO i #include che causano errori "No such file or directory"
- Output: SOLO il codice corretto completo, senza markdown, senza spiegazioni
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

        result = self.client.generate(messages, max_tokens=2048, label="M40→Generator")
        code = self._extract_code(result["response"] or result["raw"])
        return {
            "code": code,
            "thinking": result["thinking"],
            "raw": result["raw"],
        }

    def generate_globals(self, nb) -> dict:
        """
        Genera la sezione globals (#include, #define, variabili globali).
        Ritorna: {"code": str, "thinking": str}
        """
        messages = [
            {"role": "system", "content": SYSTEM_GLOBALS},
            {"role": "user", "content": nb.context_for_globals()},
        ]
        result = self.client.generate(messages, max_tokens=512, label="M40→Globals")
        code = self._extract_code(result["response"] or result["raw"])
        return {"code": code, "thinking": result["thinking"]}

    def generate_function(self, nome: str, nb) -> dict:
        """
        Genera una singola funzione Arduino.
        Ritorna: {"code": str, "thinking": str}
        """
        messages = [
            {"role": "system", "content": SYSTEM_FUNCTION},
            {"role": "user", "content": nb.context_for_function(nome)},
        ]
        result = self.client.generate(messages, max_tokens=512, label=f"M40→{nome}()")
        code = self._extract_code(result["response"] or result["raw"])
        return {"code": code, "thinking": result["thinking"]}

    def patch_code(
        self,
        code: str,
        errors: list[dict],
        analysis: str = "",
    ) -> dict:
        """
        Corregge il codice dato gli errori del compilatore.

        errors: lista di {"line": int, "type": str, "message": str}
        analysis: spiegazione degli errori dall'orchestratore (opzionale)
        ritorna: {"code": str, "thinking": str, "raw": str}
        """
        error_lines = []
        for e in errors:
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

        result = self.client.generate(messages, max_tokens=2048, label="M40→Patcher")
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
