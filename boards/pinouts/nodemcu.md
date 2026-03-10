# NodeMCU v2 (ESP8266) — Pinout e Specifiche

## Identificatori
- **arduino FQBN**: `esp8266:esp8266:nodemcuv2`
- **PlatformIO board ID**: `nodemcuv2`
- **Platform PlatformIO**: `espressif8266` (da installare: `pio platform install espressif8266`)
- **Upload baud**: 115200
- **Serial monitor baud**: 115200

## Hardware
| Parametro | Valore |
|-----------|--------|
| CPU | Xtensa L106 single-core |
| Clock | 80 MHz (overclockabile a 160 MHz) |
| Flash | 4 MB |
| RAM | 80 KB DRAM (50 KB disponibile per utente) |
| WiFi | 802.11 b/g/n 2.4 GHz |
| Bluetooth | ❌ NESSUNO |
| ADC | 1 solo canale (A0), 0-1V (0-3.3V con voltage divider su alcune board) |
| Tensione | 3.3V I/O |

## Pinout (NodeMCU v2 Amica, 30-pin)

```
                       USB (CH340)
                          |
          A0 ── [ A0   ][ RST  ] ──
          ──── [ RSV  ][ EN   ] ──
          ──── [ RSV  ][ 3V3  ] ── 3V3
    D0/GPIO16─ [ D0   ][ GND  ] ── GND
    D1/GPIO5 ─ [ D1   ][ VIN  ] ── 5V
    D2/GPIO4 ─ [ D2   ][ D9   ] ── D9/GPIO3/RX0
    D3/GPIO0 ─ [ D3   ][ D10  ] ── D10/GPIO1/TX0
    D4/GPIO2 ─ [ D4   ][ D11  ] ── D11/GPIO9
    GND ─────  [ GND  ][ D12  ] ── D12/GPIO10
    5V ──────  [ VCC  ][ D13  ] ── D13 (non standard)
               [ D5   ][ D7   ] ──
               [ D6   ][ D8   ] ──
                    USB
```

## Mappatura D→GPIO (FONDAMENTALE per NodeMCU)

| Label | GPIO | Input | Output | Note |
|-------|------|-------|--------|------|
| D0    | GPIO16 | ✅ | ✅ | No interrupt, no PWM, no I2C. Usato per deep sleep wake |
| D1    | GPIO5  | ✅ | ✅ | **I2C SCL default** |
| D2    | GPIO4  | ✅ | ✅ | **I2C SDA default** |
| D3    | GPIO0  | pull-up | ✅ | Boot mode: LOW = flash mode. Attenzione |
| D4    | GPIO2  | pull-up | ✅ | **LED onboard (ACTIVE LOW)**. Boot: HIGH richiesto |
| D5    | GPIO14 | ✅ | ✅ | **SPI SCK** |
| D6    | GPIO12 | ✅ | ✅ | **SPI MISO** |
| D7    | GPIO13 | ✅ | ✅ | **SPI MOSI** |
| D8    | GPIO15 | pull-down | ✅ | **SPI SS**. Boot: LOW richiesto |
| D9/RX | GPIO3 | ✅ | ✅ | UART RX (USB) — non usare per dati utente |
| D10/TX| GPIO1 | ✅ | ✅ | UART TX (USB) — stampa garbage al boot |
| A0    | ADC0  | ✅ | ❌ | Unico ADC, 0–1V, 10-bit (1024 steps) |

## Bus e interfacce

### I2C (Wire)
```cpp
Wire.begin(4, 5); // SDA=GPIO4/D2, SCL=GPIO5/D1 (default, puoi omettere)
```

### SPI
```cpp
SPI.begin(); // SCK=D5(GPIO14), MISO=D6(GPIO12), MOSI=D7(GPIO13), SS=D8(GPIO15)
```

### UART
```cpp
Serial.begin(115200); // UART0: TX=GPIO1/D10, RX=GPIO3/D9
// Nota: Serial stampa garbage (messaggi boot) prima di setup()
// Usa Serial.begin() in setup() con delay(100) se serve output pulito
```

### PWM
```cpp
// PWM software su qualunque pin (tranne D0/GPIO16)
analogWrite(D1, 512); // 0-1023 (10-bit)
analogWriteFrequency(1000); // frequenza Hz (default 1000)
```

### ADC
```cpp
int val = analogRead(A0); // 0-1023 (10-bit), 0-1V fisici
// Su NodeMCU Amica il voltage divider porta il range a 0-3.3V
// Su altri moduli potrebbe essere 0-1V vero
```

### DeepSleep
```cpp
ESP.deepSleep(5e6); // 5 secondi in microsecondi
// D0/GPIO16 deve essere collegato a RST per il wake!
```

## WiFi
```cpp
#include <ESP8266WiFi.h>
WiFi.begin("SSID", "password");
while (WiFi.status() != WL_CONNECTED) delay(500);
```
**Nota**: durante connessione WiFi attiva, l'ADC non funziona correttamente.

## Quirks e avvertenze

1. **D0/GPIO16**: no interrupt, no PWM, no I2C. Collegarlo a RST per deepSleep wake
2. **D3/GPIO0 e D4/GPIO2 e D8/GPIO15**: determinano la modalità di boot
   - Boot normale: D3=HIGH, D4=HIGH, D8=LOW
   - Evitare di mettere LOW D3 o D4 con hardware al boot
3. **D10/TX**: stampa il bootloader log all'avvio. Metti il ricevitore in alta impedenza durante il boot se usi questo pin
4. **RAM limitatissima**: 50KB disponibili. Usare `PROGMEM` e `F()` per stringhe costanti
5. **Un solo ADC**: nessun modo di leggere più segnali analogici senza mux esterno
6. **Tensione ADC**: la NodeMCU Amica ha voltage divider (100K/220K) → range 0-3.3V. Verificare la variante in uso
7. **Platform da installare**: per PlatformIO sul Raspberry: `pio platform install espressif8266`

## Sketch minimo
```cpp
#include <Arduino.h>

#define LED_PIN D4  // GPIO2, ACTIVE LOW

void setup() {
  Serial.begin(115200);
  delay(100);
  pinMode(LED_PIN, OUTPUT);
  Serial.println("NodeMCU pronto");
}

void loop() {
  digitalWrite(LED_PIN, LOW);  // LED ON
  delay(500);
  digitalWrite(LED_PIN, HIGH); // LED OFF
  delay(500);
}
```
