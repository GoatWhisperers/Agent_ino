# ESP32-S2 DevKit — Pinout e Specifiche

## Identificatori
- **arduino FQBN**: `esp32:esp32:esp32s2`
- **PlatformIO board ID**: `esp32-s2-saola-1`
- **Upload baud**: 921600
- **Serial monitor baud**: 115200

## Hardware
| Parametro | Valore |
|-----------|--------|
| CPU | Xtensa LX7 single-core (no dual-core!) |
| Clock | 240 MHz |
| Flash | 4 MB |
| RAM | 320 KB DRAM |
| PSRAM | 2 MB (su alcuni moduli) |
| WiFi | 802.11 b/g/n 2.4 GHz |
| Bluetooth | ❌ NESSUNO (differenza fondamentale da ESP32) |
| USB | ✅ USB OTG nativo (CDC, HID, MSC) |
| Tensione | 3.3V I/O |

## Differenze chiave da ESP32-WROOM
- **NO Bluetooth** (né Classic né BLE)
- **USB nativo** integrato nel chip (puoi fare HID, CDC senza chip extra)
- CPU **single-core** (meno parallelismo)
- **ADC migliorato**: ADC2 usabile anche con WiFi (a differenza del WROOM)
- Più pin touch (14 vs 10)
- Pin DAC: solo GPIO17, GPIO18

## Pinout (ESP32-S2-Saola-1, 30-pin)

```
                USB (nativo chip)       USB (UART CH340)
                     |                        |
    3V3 ─── [ 3V3  ] [ GND ] ─── GND
         ─── [ 1   ] [ 2   ] ─── (ADC1 ch1)
         ─── [ 3   ] [ 4   ] ─── (ADC1 ch3)
         ─── [ 5   ] [ 6   ] ─── (ADC1 ch5)
         ─── [ 7   ] [ 8   ] ─── (ADC1 ch7)
         ─── [ 9   ] [ 10  ] ─── (ADC1 ch9)
         ─── [ 11  ] [ 12  ] ─── (ADC2 ch1)
         ─── [ 13  ] [ 14  ] ─── (ADC2 ch3)
         ─── [ 15  ] [ 16  ] ─── (ADC2 ch5)
         ─── [ 17/DAC1 ] [ 18/DAC2 ] ───
         ─── [ 19  ] [ 20  ] ───
         ─── [ 21/SDA] [ 22/SCL] ───
         ─── [ 23/MOSI] [ 24 ] ───
MISO ─── [ 37  ] [ 36  ] ─── SCK
  SS ─── [ 34  ] [ 35  ] ───
LED ──── [ 18  ] (LED onboard sul Saola-1)
```

## Tabella PIN principale

| GPIO | ADC | DAC | Touch | PWM | Note |
|------|-----|-----|-------|-----|------|
| 1    | ADC1 ch0 | — | T1 | ✅ | |
| 2    | ADC1 ch1 | — | T2 | ✅ | |
| 3    | ADC1 ch2 | — | T3 | ✅ | |
| 4    | ADC1 ch3 | — | T4 | ✅ | |
| 5    | ADC1 ch4 | — | T5 | ✅ | |
| 6    | ADC1 ch5 | — | T6 | ✅ | |
| 7    | ADC1 ch6 | — | T7 | ✅ | |
| 8    | ADC1 ch7 | — | T8 | ✅ | LED onboard (Saola-1) |
| 9    | ADC1 ch8 | — | T9 | ✅ | |
| 10   | ADC1 ch9 | — | T10| ✅ | |
| 11   | ADC2 ch0 | — | T11| ✅ | |
| 12   | ADC2 ch1 | — | T12| ✅ | |
| 13   | ADC2 ch2 | — | T13| ✅ | |
| 14   | ADC2 ch3 | — | T14| ✅ | |
| 15   | ADC2 ch4 | — | — | ✅ | |
| 16   | ADC2 ch5 | — | — | ✅ | |
| 17   | ADC2 ch6 | DAC1 | — | ✅ | DAC output |
| 18   | ADC2 ch7 | DAC2 | — | ✅ | DAC output |
| 19   | ADC2 ch8 | — | — | ✅ | USB D- (non usare se usi USB) |
| 20   | ADC2 ch9 | — | — | ✅ | USB D+ (non usare se usi USB) |
| 21   | —  | — | — | ✅ | I2C SDA default |
| 22   | —  | — | — | ✅ | I2C SCL default |
| 23   | —  | — | — | ✅ | SPI MOSI default |
| 33-42 | — | — | — | ✅ | GPIO extra |

## Bus e interfacce

### I2C
```cpp
Wire.begin(21, 22); // SDA=21, SCL=22
```

### SPI
```cpp
SPI.begin(36, 37, 35, 34); // SCK, MISO, MOSI, SS
```

### UART
```cpp
Serial.begin(115200);         // UART0 via USB UART chip
Serial1.begin(9600, SERIAL_8N1, RX_PIN, TX_PIN);
```

### USB nativo (CDC)
```cpp
// In platformio.ini aggiungere: build_flags = -DARDUINO_USB_CDC_ON_BOOT=1
USB.begin();
Serial.begin(115200); // ora è USB CDC, non UART
```

### USB HID (tastiera, mouse)
```cpp
#include "USB.h"
#include "USBHIDKeyboard.h"
USBHIDKeyboard Keyboard;
USB.begin();
Keyboard.begin();
Keyboard.print("Hello!");
```

## Quirks e avvertenze

1. **No Bluetooth**: se serve BT usare ESP32-WROOM
2. **GPIO 19-20**: riservati USB D-/D+, evitare se si usa USB nativo
3. **GPIO 26-32**: connessi alla flash — NON USARE
4. **ADC2 + WiFi**: sull'S2 ADC2 funziona anche con WiFi (miglioramento rispetto al WROOM)
5. **Single core**: task intensivi vanno schedulati con attenzione (no FreeRTOS su Core 1)
