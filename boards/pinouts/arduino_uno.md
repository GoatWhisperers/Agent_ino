# Arduino Uno (ATmega328P) — Pinout e Specifiche

## Identificatori
- **arduino FQBN**: `arduino:avr:uno`
- **PlatformIO board ID**: `uno`
- **Upload baud**: 115200
- **Serial monitor baud**: 9600 (convenzione; puoi usare 115200)

## Hardware
| Parametro | Valore |
|-----------|--------|
| MCU | ATmega328P |
| Clock | 16 MHz |
| Flash | 32 KB (0.5 KB bootloader) |
| RAM (SRAM) | 2 KB ← LIMITE CRITICO |
| EEPROM | 1 KB |
| Tensione I/O | 5V |
| Tensione alimentazione | 7–12V (jack), 5V (USB) |
| Corrente per pin | 40 mA (max), 200 mA totale |

## Pinout

```
                     USB (ATmega16U2)
                         |
RESET  ── [ RST ]                    [ AREF ] ── AREF
   5V ── [ 3.3V]                    [ GND  ] ── GND
   ──── [ 5V  ]                    [ 13/SCK/LED ] ── D13
  GND ── [ GND ]                    [ 12/MISO   ] ── D12
  GND ── [ GND ]                    [ 11~/MOSI  ] ── D11 (PWM)
  VIN ── [ VIN ]                    [ 10~/SS    ] ── D10 (PWM)
                                     [  9~       ] ── D9  (PWM)
   A0 ── [ A0  ]                    [  8        ] ── D8
   A1 ── [ A1  ]                    [  7        ] ── D7
   A2 ── [ A2  ]                    [  6~       ] ── D6  (PWM)
   A3 ── [ A3  ]                    [  5~       ] ── D5  (PWM)
A4/SDA── [ A4  ]                    [  4        ] ── D4
A5/SCL── [ A5  ]                    [  3~/INT1  ] ── D3  (PWM, interrupt)
                                     [  2/INT0   ] ── D2  (interrupt)
                                     [  1/TX     ] ── D1  (Serial TX)
                                     [  0/RX     ] ── D0  (Serial RX)
```

## Tabella PIN completa

| Pin   | GPIO | PWM | Interrupt | Funzione speciale | Note |
|-------|------|-----|-----------|-------------------|------|
| D0    | PD0  | ❌  | ❌        | RX (Serial)       | Evitare se usi Serial |
| D1    | PD1  | ❌  | ❌        | TX (Serial)       | Evitare se usi Serial |
| D2    | PD2  | ❌  | INT0      | Interrupt esterno | |
| D3    | PD3  | ✅  | INT1      | Interrupt esterno | |
| D4    | PD4  | ❌  | ❌        | —                 | |
| D5    | PD5  | ✅  | ❌        | —                 | |
| D6    | PD6  | ✅  | ❌        | —                 | |
| D7    | PD7  | ❌  | ❌        | —                 | |
| D8    | PB0  | ❌  | ❌        | —                 | |
| D9    | PB1  | ✅  | ❌        | —                 | |
| D10   | PB2  | ✅  | ❌        | SPI SS            | |
| D11   | PB3  | ✅  | ❌        | SPI MOSI          | |
| D12   | PB4  | ❌  | ❌        | SPI MISO          | |
| D13   | PB5  | ❌  | ❌        | SPI SCK, LED      | LED onboard |
| A0    | PC0  | ❌  | ❌        | Analogico (D14)   | 10-bit ADC, 0-5V |
| A1    | PC1  | ❌  | ❌        | Analogico (D15)   | 10-bit ADC, 0-5V |
| A2    | PC2  | ❌  | ❌        | Analogico (D16)   | 10-bit ADC, 0-5V |
| A3    | PC3  | ❌  | ❌        | Analogico (D17)   | 10-bit ADC, 0-5V |
| A4    | PC4  | ❌  | ❌        | I2C SDA (D18)     | |
| A5    | PC5  | ❌  | ❌        | I2C SCL (D19)     | |

**Pin PWM** (tilde ~ nella serigrafia): D3, D5, D6, D9, D10, D11

## Bus e interfacce

### Serial (UART)
```cpp
Serial.begin(9600);  // TX=D1, RX=D0
// Nota: D0 e D1 condivisi con USB. Usare SoftwareSerial per una seconda porta
#include <SoftwareSerial.h>
SoftwareSerial mySerial(8, 9); // RX, TX
mySerial.begin(9600);
```

### I2C (Wire)
```cpp
#include <Wire.h>
Wire.begin(); // SDA=A4, SCL=A5
Wire.beginTransmission(0x27);
Wire.write(data);
Wire.endTransmission();
```

### SPI
```cpp
#include <SPI.h>
SPI.begin(); // SCK=D13, MISO=D12, MOSI=D11, SS=D10
```

### PWM
```cpp
analogWrite(9, 128); // 0-255, ~490Hz (D5,D6=980Hz, D3,D9,D10,D11=490Hz)
```

### ADC
```cpp
int val = analogRead(A0); // 0-1023 (10-bit), 0-5V
analogReference(DEFAULT);   // 5V reference
analogReference(INTERNAL);  // 1.1V reference interna
analogReference(EXTERNAL);  // tensione su AREF pin
```

### EEPROM
```cpp
#include <EEPROM.h>
EEPROM.write(addr, value);   // byte, addr 0-1023
byte val = EEPROM.read(addr);
EEPROM.put(addr, myStruct);  // qualunque tipo
EEPROM.get(addr, myStruct);
```

## Gestione RAM (CRITICA — solo 2KB!)

```cpp
// ❌ SBAGLIATO: stringa in RAM
Serial.println("Messaggio lungo che occupa RAM");

// ✅ CORRETTO: stringa in Flash con F()
Serial.println(F("Messaggio lungo che occupa Flash"));

// ❌ Array grande:
char buf[512]; // occupa 25% della RAM totale!

// Verifica RAM disponibile:
Serial.println(freeMemory()); // richiede MemoryFree library
```

## Quirks e avvertenze

1. **2KB RAM**: limite più comune di problemi. Ogni `String` object consuma RAM extra. Preferire `char[]` e `F()` per literal
2. **D0/D1**: condivisi con USB Serial. Durante upload il PC usa questi pin — non collegare hardware che li driver durante l'upload
3. **Tensione 5V**: compatibile con molti sensori 5V, ma non con ESP32/RPi (3.3V). Usa voltage divider o level shifter se colleghi a 3.3V
4. **analogWrite non è vero PWM su tutti i pin**: frequenze diverse (490Hz vs 980Hz su D5/D6)
5. **Interrupt**: solo D2 (INT0) e D3 (INT1) per interrupt esterni. `attachInterrupt(digitalPinToInterrupt(2), handler, FALLING)`
6. **Nessun WiFi/BT**: per connettività, aggiungere modulo ESP8266 (ESP-01) via SoftwareSerial

## Sketch minimo
```cpp
void setup() {
  Serial.begin(9600);
  pinMode(13, OUTPUT); // LED
  Serial.println(F("Arduino Uno pronto"));
}

void loop() {
  digitalWrite(13, HIGH);
  delay(1000);
  digitalWrite(13, LOW);
  delay(1000);
}
```
