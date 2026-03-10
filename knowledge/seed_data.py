"""
Popola il DB con dati iniziali:
- Librerie comuni per Arduino
- Errori comuni e relative fix
- Snippet di esempio
"""
import sys
sys.path.insert(0, '/home/lele/codex-openai/programmatore_di_arduini')

from knowledge.db import (
    init_db,
    add_library,
    add_error_fix,
    add_snippet,
)
from knowledge.semantic import index_snippet


def seed_libraries():
    """Inserisce le librerie Arduino più comuni."""
    libraries = [
        {
            "name": "DHT sensor library",
            "version": "1.4.6",
            "include": '#include "DHT.h"',
            "install_cmd": 'arduino-cli lib install "DHT sensor library"',
            "description": "Libreria per sensori DHT11 e DHT22 (temperatura e umidità)",
            "example": (
                '#include "DHT.h"\n'
                "#define DHTPIN 2\n"
                "#define DHTTYPE DHT22\n"
                "DHT dht(DHTPIN, DHTTYPE);\n"
                "void setup() { Serial.begin(9600); dht.begin(); }\n"
                "void loop() {\n"
                "  float h = dht.readHumidity();\n"
                "  float t = dht.readTemperature();\n"
                '  Serial.print("T:"); Serial.print(t);\n'
                '  Serial.print(" H:"); Serial.println(h);\n'
                "  delay(2000);\n"
                "}"
            ),
        },
        {
            "name": "Servo",
            "version": "1.2.1",
            "include": "#include <Servo.h>",
            "install_cmd": 'arduino-cli lib install "Servo"',
            "description": "Controlla servo motori tramite PWM",
            "example": (
                "#include <Servo.h>\n"
                "Servo myservo;\n"
                "void setup() { myservo.attach(9); }\n"
                "void loop() {\n"
                "  myservo.write(0);   delay(1000);\n"
                "  myservo.write(90);  delay(1000);\n"
                "  myservo.write(180); delay(1000);\n"
                "}"
            ),
        },
        {
            "name": "Wire",
            "version": "built-in",
            "include": "#include <Wire.h>",
            "install_cmd": "built-in (no install needed)",
            "description": "Comunicazione I2C tra Arduino e periferiche",
            "example": (
                "#include <Wire.h>\n"
                "void setup() {\n"
                "  Wire.begin();\n"
                "  Serial.begin(9600);\n"
                "}\n"
                "void loop() {\n"
                "  Wire.beginTransmission(0x68);\n"
                "  Wire.write(0x3B);\n"
                "  Wire.endTransmission(false);\n"
                "  Wire.requestFrom(0x68, 6, true);\n"
                "}"
            ),
        },
        {
            "name": "SPI",
            "version": "built-in",
            "include": "#include <SPI.h>",
            "install_cmd": "built-in (no install needed)",
            "description": "Comunicazione SPI (Serial Peripheral Interface)",
            "example": (
                "#include <SPI.h>\n"
                "const int CS_PIN = 10;\n"
                "void setup() {\n"
                "  SPI.begin();\n"
                "  pinMode(CS_PIN, OUTPUT);\n"
                "  digitalWrite(CS_PIN, HIGH);\n"
                "}"
            ),
        },
        {
            "name": "EEPROM",
            "version": "built-in",
            "include": "#include <EEPROM.h>",
            "install_cmd": "built-in (no install needed)",
            "description": "Lettura e scrittura sulla memoria EEPROM interna",
            "example": (
                "#include <EEPROM.h>\n"
                "void setup() {\n"
                "  EEPROM.write(0, 42);\n"
                "  int val = EEPROM.read(0);\n"
                "  Serial.begin(9600);\n"
                "  Serial.println(val);\n"
                "}"
            ),
        },
        {
            "name": "SoftwareSerial",
            "version": "built-in",
            "include": "#include <SoftwareSerial.h>",
            "install_cmd": "built-in (no install needed)",
            "description": "Porta seriale software su pin digitali arbitrari",
            "example": (
                "#include <SoftwareSerial.h>\n"
                "SoftwareSerial mySerial(10, 11); // RX, TX\n"
                "void setup() {\n"
                "  Serial.begin(9600);\n"
                "  mySerial.begin(9600);\n"
                "}\n"
                "void loop() {\n"
                '  if (mySerial.available()) Serial.write(mySerial.read());\n'
                '  if (Serial.available()) mySerial.write(Serial.read());\n'
                "}"
            ),
        },
        {
            "name": "LiquidCrystal",
            "version": "1.0.7",
            "include": "#include <LiquidCrystal.h>",
            "install_cmd": 'arduino-cli lib install "LiquidCrystal"',
            "description": "Controlla display LCD compatibili HD44780",
            "example": (
                "#include <LiquidCrystal.h>\n"
                "LiquidCrystal lcd(12, 11, 5, 4, 3, 2);\n"
                "void setup() {\n"
                "  lcd.begin(16, 2);\n"
                '  lcd.print("Hello Arduino!");\n'
                "}\n"
                "void loop() {}"
            ),
        },
        {
            "name": "Adafruit NeoPixel",
            "version": "1.12.0",
            "include": "#include <Adafruit_NeoPixel.h>",
            "install_cmd": 'arduino-cli lib install "Adafruit NeoPixel"',
            "description": "Controlla LED RGB WS2812B (NeoPixel) in strip e matrici",
            "example": (
                "#include <Adafruit_NeoPixel.h>\n"
                "#define PIN 6\n"
                "#define NUMPIXELS 8\n"
                "Adafruit_NeoPixel pixels(NUMPIXELS, PIN, NEO_GRB + NEO_KHZ800);\n"
                "void setup() { pixels.begin(); }\n"
                "void loop() {\n"
                "  for(int i=0; i<NUMPIXELS; i++) {\n"
                "    pixels.setPixelColor(i, pixels.Color(255, 0, 0));\n"
                "  }\n"
                "  pixels.show();\n"
                "  delay(500);\n"
                "}"
            ),
        },
    ]

    for lib in libraries:
        add_library(
            name=lib["name"],
            version=lib.get("version"),
            include=lib.get("include"),
            install_cmd=lib.get("install_cmd"),
            description=lib.get("description"),
            example=lib.get("example"),
            source="manual",
        )
    print(f"[seed] Inserite {len(libraries)} librerie")


def seed_error_fixes():
    """Inserisce gli errori Arduino più comuni con le relative fix."""
    errors = [
        {
            "pattern": "was not declared in this scope",
            "cause": "Variabile o funzione usata prima di essere dichiarata, o fuori scope",
            "fix_description": (
                "Assicurati di dichiarare la variabile/funzione prima di usarla. "
                "Controlla che le variabili globali siano dichiarate fuori da setup() e loop(). "
                "Verifica che l'header della libreria necessaria sia incluso."
            ),
            "fix_patch": (
                "// SBAGLIATO:\n"
                "void loop() { myVar = 5; }  // myVar non dichiarata\n\n"
                "// CORRETTO:\n"
                "int myVar = 0;  // dichiarazione globale\n"
                "void loop() { myVar = 5; }"
            ),
        },
        {
            "pattern": "expected ';' before",
            "cause": "Punto e virgola mancante alla fine di un'istruzione",
            "fix_description": (
                "Aggiungi il punto e virgola ';' alla fine dell'istruzione indicata "
                "dall'errore o alla riga precedente."
            ),
            "fix_patch": (
                "// SBAGLIATO:\n"
                "int x = 5\n"
                "// CORRETTO:\n"
                "int x = 5;"
            ),
        },
        {
            "pattern": "no matching function for call to",
            "cause": "Chiamata a funzione con argomenti di tipo o numero errato",
            "fix_description": (
                "Controlla la firma della funzione nella documentazione della libreria. "
                "Verifica i tipi degli argomenti (es. int vs float vs String). "
                "Assicurati che il numero di parametri sia corretto."
            ),
            "fix_patch": (
                "// Esempio con DHT:\n"
                "// SBAGLIATO: DHT dht(2);\n"
                "// CORRETTO:  DHT dht(2, DHT22);"
            ),
        },
        {
            "pattern": "does not name a type",
            "cause": "Tipo non riconosciuto: libreria non inclusa o typo nel nome del tipo",
            "fix_description": (
                "Verifica di aver incluso l'header della libreria che definisce il tipo. "
                "Controlla l'ortografia del tipo. "
                "Assicurati che la libreria sia installata con arduino-cli."
            ),
            "fix_patch": (
                "// SBAGLIATO (senza include):\n"
                "Servo myServo;\n\n"
                "// CORRETTO:\n"
                "#include <Servo.h>\n"
                "Servo myServo;"
            ),
        },
        {
            "pattern": "undefined reference to",
            "cause": "Funzione dichiarata ma non definita, o libreria non linkata",
            "fix_description": (
                "Controlla che la libreria sia correttamente installata e inclusa. "
                "Se hai dichiarato una funzione custom, assicurati di averla definita. "
                "In Arduino IDE/CLI, tutte le librerie nell'include vengono linkate automaticamente."
            ),
            "fix_patch": None,
        },
        {
            "pattern": "invalid conversion from",
            "cause": "Conversione implicita non permessa tra tipi (es. char* a String)",
            "fix_description": (
                "Usa un cast esplicito o la funzione di conversione appropriata. "
                "Esempio: String(myCharArray) per convertire char[] in String."
            ),
            "fix_patch": (
                "// SBAGLIATO:\n"
                "String s = myCharPointer;\n\n"
                "// CORRETTO:\n"
                "String s = String(myCharPointer);"
            ),
        },
        {
            "pattern": "analogRead",
            "cause": "Uso errato di analogRead: pin digitale usato come analogico o viceversa",
            "fix_description": (
                "Su Arduino Uno i pin analogici sono A0-A5. "
                "Usa analogRead(A0) non analogRead(0) per il pin A0."
            ),
            "fix_patch": (
                "// SBAGLIATO:\n"
                "int val = analogRead(0);  // ambiguo\n\n"
                "// CORRETTO:\n"
                "int val = analogRead(A0);  // esplicito"
            ),
        },
        {
            "pattern": "loop() must be defined",
            "cause": "La funzione loop() obbligatoria è assente",
            "fix_description": (
                "Ogni sketch Arduino deve avere sia setup() che loop(). "
                "Se loop() non fa niente, lasciala vuota: void loop() {}"
            ),
            "fix_patch": (
                "void setup() { /* init */ }\n"
                "void loop() { /* obbligatoria, può essere vuota */ }"
            ),
        },
    ]

    for e in errors:
        add_error_fix(
            pattern=e["pattern"],
            cause=e["cause"],
            fix_description=e["fix_description"],
            fix_patch=e.get("fix_patch"),
        )
    print(f"[seed] Inseriti {len(errors)} error fix")


def seed_snippets():
    """Inserisce snippet di esempio comuni."""
    snippets = [
        {
            "task": "far lampeggiare LED sul pin 13 (Blink base)",
            "code": (
                "void setup() {\n"
                "  pinMode(13, OUTPUT);\n"
                "}\n\n"
                "void loop() {\n"
                "  digitalWrite(13, HIGH);\n"
                "  delay(1000);\n"
                "  digitalWrite(13, LOW);\n"
                "  delay(1000);\n"
                "}"
            ),
            "board": "arduino:avr:uno",
            "libraries": [],
            "tags": ["led", "blink", "base", "output", "digitalwrite"],
        },
        {
            "task": "leggere temperatura e umidità con sensore DHT22",
            "code": (
                '#include "DHT.h"\n\n'
                "#define DHTPIN 2\n"
                "#define DHTTYPE DHT22\n\n"
                "DHT dht(DHTPIN, DHTTYPE);\n\n"
                "void setup() {\n"
                "  Serial.begin(9600);\n"
                "  dht.begin();\n"
                "}\n\n"
                "void loop() {\n"
                "  float humidity = dht.readHumidity();\n"
                "  float temperature = dht.readTemperature();\n"
                "  if (isnan(humidity) || isnan(temperature)) {\n"
                '    Serial.println("Errore lettura DHT!");\n'
                "    return;\n"
                "  }\n"
                '  Serial.print("Temperatura: ");\n'
                "  Serial.print(temperature);\n"
                '  Serial.print(" C  Umidita: ");\n'
                "  Serial.print(humidity);\n"
                '  Serial.println(" %");\n'
                "  delay(2000);\n"
                "}"
            ),
            "board": "arduino:avr:uno",
            "libraries": ["DHT sensor library"],
            "tags": ["dht22", "temperatura", "umidità", "sensore", "serial"],
        },
        {
            "task": "controllare un servo motore con potenziometro",
            "code": (
                "#include <Servo.h>\n\n"
                "Servo myservo;\n"
                "int potpin = A0;\n\n"
                "void setup() {\n"
                "  myservo.attach(9);\n"
                "}\n\n"
                "void loop() {\n"
                "  int val = analogRead(potpin);\n"
                "  val = map(val, 0, 1023, 0, 180);\n"
                "  myservo.write(val);\n"
                "  delay(15);\n"
                "}"
            ),
            "board": "arduino:avr:uno",
            "libraries": ["Servo"],
            "tags": ["servo", "potenziometro", "analogread", "map"],
        },
        {
            "task": "accendere LED con pulsante (button)",
            "code": (
                "const int buttonPin = 2;\n"
                "const int ledPin = 13;\n\n"
                "void setup() {\n"
                "  pinMode(buttonPin, INPUT_PULLUP);\n"
                "  pinMode(ledPin, OUTPUT);\n"
                "}\n\n"
                "void loop() {\n"
                "  int buttonState = digitalRead(buttonPin);\n"
                "  if (buttonState == LOW) {\n"
                "    digitalWrite(ledPin, HIGH);\n"
                "  } else {\n"
                "    digitalWrite(ledPin, LOW);\n"
                "  }\n"
                "}"
            ),
            "board": "arduino:avr:uno",
            "libraries": [],
            "tags": ["button", "pulsante", "led", "input_pullup", "digitalread"],
        },
        {
            "task": "leggere valore analogico e stampare su seriale",
            "code": (
                "void setup() {\n"
                "  Serial.begin(9600);\n"
                "}\n\n"
                "void loop() {\n"
                "  int sensorValue = analogRead(A0);\n"
                "  float voltage = sensorValue * (5.0 / 1023.0);\n"
                '  Serial.print("Valore: ");\n'
                "  Serial.print(sensorValue);\n"
                '  Serial.print("  Tensione: ");\n'
                "  Serial.println(voltage);\n"
                "  delay(100);\n"
                "}"
            ),
            "board": "arduino:avr:uno",
            "libraries": [],
            "tags": ["analogread", "seriale", "tensione", "sensore", "serial"],
        },
    ]

    indexed = 0
    for s in snippets:
        sid = add_snippet(
            task=s["task"],
            code=s["code"],
            board=s["board"],
            libraries=s["libraries"],
            tags=s["tags"],
        )
        try:
            index_snippet(sid, s["task"], s["code"], s["tags"])
            indexed += 1
        except Exception as e:
            print(f"  [warn] Index fallito per '{s['task']}': {e}")
    print(f"[seed] Inseriti {len(snippets)} snippet ({indexed} indicizzati in ChromaDB)")


if __name__ == "__main__":
    print("[seed] Inizializzazione DB...")
    init_db()
    print("[seed] Inserimento librerie...")
    seed_libraries()
    print("[seed] Inserimento error fix...")
    seed_error_fixes()
    print("[seed] Inserimento snippet di esempio...")
    seed_snippets()
    print("[seed] Completato!")
