# ESP32-WROOM-32 DevKit — Pinout e Specifiche

## Identificatori
- **arduino FQBN**: `esp32:esp32:esp32`
- **PlatformIO board ID**: `esp32dev`
- **Upload baud**: 921600
- **Serial monitor baud**: 115200

## Hardware
| Parametro | Valore |
|-----------|--------|
| CPU | Xtensa LX6 dual-core |
| Clock | 240 MHz |
| Flash | 4 MB |
| RAM | 320 KB DRAM + 200 KB IRAM = 520 KB totali |
| EEPROM emulata | su flash (Preferences o EEPROM.h) |
| WiFi | 802.11 b/g/n 2.4 GHz |
| Bluetooth | BT Classic 4.2 + BLE |
| Tensione | 3.3V I/O (NON tolera 5V!) |

## Pinout — Vista dall'alto (30-pin DevKit)

```
                    USB
            [ EN ]      [ GND ]
     3V3 — [ 3V3 ]    [ D23/MOSI ] — 23
     GND — [ GND ]    [ D22/SCL  ] — 22
     D1  — [ TX0 ]    [ TX/D1    ] — 1
     D3  — [ RX0 ]    [ RX/D3    ] — 3
     D21 — [ D21/SDA] [ D19/MISO ] — 19
     D19 — [ D19 ]    [ D18/SCK  ] — 18
     D18 — [ D18 ]    [ D5/SS    ] — 5
     D5  — [ D5  ]    [ D17/TX2  ] — 17
     D17 — [ TX2 ]    [ D16/RX2  ] — 16
     D16 — [ RX2 ]    [ D4       ] — 4
     D4  — [ D4  ]    [ D2/LED   ] — 2  ← LED blu onboard
     D2  — [ D2  ]    [ D15      ] — 15
     D15 — [ D15 ]    [ GND      ]
     GND — [ GND ]    [ D13      ] — 13
     D13 — [ D13 ]    [ D12      ] — 12
     D12 — [ D12 ]    [ D14      ] — 14
     D14 — [ D14 ]    [ D27      ] — 27
     D27 — [ D27 ]    [ D26/DAC2 ] — 26
     D26 — [ D26 ]    [ D25/DAC1 ] — 25
     D25 — [ D25 ]    [ D33      ] — 33
     D33 — [ D33 ]    [ D32      ] — 32
     D32 — [ D32 ]    [ D35/ADC  ] — 35 (input-only)
     D35 — [ D35 ]    [ D34/ADC  ] — 34 (input-only)
     D34 — [ D34 ]    [ VN/D39   ] — 39 (input-only)
     D39 — [ VN  ]    [ VP/D36   ] — 36 (input-only)
     D36 — [ VP  ]    [ EN       ]
            [ GND ]      [ 3V3 ]
                    USB
```

## Tabella PIN completa

| GPIO | Nome     | Input | Output | ADC | DAC | Touch | PWM | Note |
|------|----------|-------|--------|-----|-----|-------|-----|------|
| 0    | D0       | ✅    | ✅     | ADC2 | —  | T1   | ✅  | Boot mode (tieni HIGH al boot) |
| 1    | TX0      | ✅    | ✅     | —   | —   | —    | ✅  | USB Serial TX |
| 2    | D2/LED   | ✅    | ✅     | ADC2 | —  | T2   | ✅  | LED onboard (HIGH=acceso) |
| 3    | RX0      | ✅    | ✅     | —   | —   | —    | ✅  | USB Serial RX |
| 4    | D4       | ✅    | ✅     | ADC2 | —  | T0   | ✅  | |
| 5    | D5/SS    | ✅    | ✅     | —   | —   | —    | ✅  | SPI SS default |
| 12   | D12/MISO2| ✅    | ✅     | ADC2 | —  | T5   | ✅  | Boot mode (tieni LOW al boot) |
| 13   | D13      | ✅    | ✅     | ADC2 | —  | T4   | ✅  | |
| 14   | D14/SCK2 | ✅    | ✅     | ADC2 | —  | T6   | ✅  | |
| 15   | D15/SS2  | ✅    | ✅     | ADC2 | —  | T3   | ✅  | Boot mode (tieni HIGH al boot) |
| 16   | RX2      | ✅    | ✅     | —   | —   | —    | ✅  | UART2 RX |
| 17   | TX2      | ✅    | ✅     | —   | —   | —    | ✅  | UART2 TX |
| 18   | SCK/D18  | ✅    | ✅     | —   | —   | —    | ✅  | SPI SCK default |
| 19   | MISO/D19 | ✅    | ✅     | —   | —   | —    | ✅  | SPI MISO default |
| 21   | SDA/D21  | ✅    | ✅     | —   | —   | —    | ✅  | I2C SDA default |
| 22   | SCL/D22  | ✅    | ✅     | —   | —   | —    | ✅  | I2C SCL default |
| 23   | MOSI/D23 | ✅    | ✅     | —   | —   | —    | ✅  | SPI MOSI default |
| 25   | D25/DAC1 | ✅    | ✅     | ADC2 | DAC1 | — | ✅  | DAC output |
| 26   | D26/DAC2 | ✅    | ✅     | ADC2 | DAC2 | — | ✅  | DAC output |
| 27   | D27      | ✅    | ✅     | ADC2 | —   | T7  | ✅  | |
| 32   | D32      | ✅    | ✅     | ADC1 | —   | T9  | ✅  | |
| 33   | D33      | ✅    | ✅     | ADC1 | —   | T8  | ✅  | |
| 34   | D34      | ✅    | ❌     | ADC1 | —   | —   | ❌  | Input-only, no pullup |
| 35   | D35      | ✅    | ❌     | ADC1 | —   | —   | ❌  | Input-only, no pullup |
| 36   | VP/D36   | ✅    | ❌     | ADC1 | —   | —   | ❌  | Input-only |
| 39   | VN/D39   | ✅    | ❌     | ADC1 | —   | —   | ❌  | Input-only |

## Bus e interfacce

### I2C (Wire)
```cpp
Wire.begin(21, 22);  // SDA=21, SCL=22 (default)
// Puoi usare qualunque GPIO:
Wire.begin(SDA_PIN, SCL_PIN);
```

### SPI
```cpp
SPI.begin(18, 19, 23, 5);  // SCK, MISO, MOSI, SS (default)
```

### UART
| Serial | TX | RX | Uso tipico |
|--------|----|----|-----------|
| Serial  (0) | 1  | 3  | USB/debug (non usare per dati) |
| Serial1 (1) | 10 | 9  | Generico |
| Serial2 (2) | 17 | 16 | Generico |
```cpp
Serial2.begin(9600, SERIAL_8N1, 16, 17); // RX=16, TX=17
```

### PWM (LEDC)
```cpp
ledcSetup(channel, freq_hz, resolution_bits); // es: ledcSetup(0, 5000, 8)
ledcAttachPin(pin, channel);
ledcWrite(channel, duty); // 0-255 per 8-bit
```

### ADC
- **ADC1** (GPIO 32, 33, 34, 35, 36, 39): funziona sempre, anche con WiFi attivo
- **ADC2** (GPIO 0, 2, 4, 12-15, 25-27): **NON USABILE durante WiFi attivo**
```cpp
int val = analogRead(34); // 0-4095 (12-bit)
analogSetAttenuation(ADC_11db); // range 0-3.6V
```

### DAC
```cpp
dacWrite(25, 128); // GPIO25 o GPIO26, valore 0-255 → 0-3.3V
```

### Touch
```cpp
int val = touchRead(4); // GPIO con touch (T0-T9)
// Valore basso = tocco rilevato
```

## Quirks e avvertenze

1. **GPIO 6-11**: connessi alla flash SPI interna — NON USARE
2. **GPIO 34, 35, 36, 39**: input-only, niente pullup/pulldown hardware
3. **ADC2 + WiFi**: se usi WiFi, usa solo ADC1 (GPIO 32-39)
4. **GPIO 0, 2, 12, 15**: usati per boot mode — attenzione se connetti hardware
5. **Tensione 3.3V**: I/O non sono 5V-tolerant. Usa level shifter se colleghi a 5V
6. **Corrente per pin**: max 40mA per pin, 1200mA totale chip

## Sketch minimo
```cpp
void setup() {
  Serial.begin(115200);
  pinMode(2, OUTPUT); // LED
}

void loop() {
  digitalWrite(2, HIGH);
  delay(500);
  digitalWrite(2, LOW);
  delay(500);
}
```
