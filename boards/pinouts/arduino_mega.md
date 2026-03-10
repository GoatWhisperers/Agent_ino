# Arduino Mega 2560 — Pinout e Specifiche

## Identificatori
- **arduino FQBN**: `arduino:avr:mega:cpu=atmega2560`
- **PlatformIO board ID**: `megaatmega2560`
- **Upload baud**: 115200
- **Serial monitor baud**: 9600

## Hardware
| Parametro | Valore |
|-----------|--------|
| MCU | ATmega2560 |
| Clock | 16 MHz |
| Flash | 256 KB (8 KB bootloader) |
| RAM (SRAM) | 8 KB |
| EEPROM | 4 KB |
| Tensione I/O | 5V |
| Pin digitali | 54 (D0–D53) |
| Pin analogici | 16 (A0–A15) |
| Pin PWM | 15 (D2–D13, D44, D45, D46) |
| Porte UART | 4 hardware (Serial 0/1/2/3) |

## Layout fisico (vista dall'alto)

```
USB ──────────────────────────── Power jack
 │                                     │
[D0-D13]  [D14-D21]  [D22-D53]  [GND/5V/3.3V/AREF]
[A0-A15]              [SDA/SCL]
```

## Tabella PIN — Digitali e PWM

| Pin  | PWM | UART | Note |
|------|-----|------|------|
| D0   | ❌  | Serial0 RX | Condiviso con USB |
| D1   | ❌  | Serial0 TX | Condiviso con USB |
| D2   | ✅  | —    | Interrupt INT4 |
| D3   | ✅  | —    | Interrupt INT5 |
| D4   | ✅  | —    | |
| D5   | ✅  | —    | |
| D6   | ✅  | —    | |
| D7   | ✅  | —    | |
| D8   | ✅  | —    | |
| D9   | ✅  | —    | |
| D10  | ✅  | —    | |
| D11  | ✅  | —    | SPI MOSI |
| D12  | ✅  | —    | SPI MISO |
| D13  | ✅  | —    | SPI SCK, LED onboard |
| D14  | ❌  | Serial3 TX | |
| D15  | ❌  | Serial3 RX | |
| D16  | ❌  | Serial2 TX | |
| D17  | ❌  | Serial2 RX | |
| D18  | ❌  | Serial1 TX | Interrupt INT3 |
| D19  | ❌  | Serial1 RX | Interrupt INT2 |
| D20  | ❌  | **I2C SDA** | Interrupt INT1 |
| D21  | ❌  | **I2C SCL** | Interrupt INT0 |
| D22–D53 | ❌ | — | GPIO digitali generici |
| D44  | ✅  | — | PWM |
| D45  | ✅  | — | PWM |
| D46  | ✅  | — | PWM |
| D50  | ❌  | — | SPI MISO |
| D51  | ❌  | — | SPI MOSI |
| D52  | ❌  | — | SPI SCK |
| D53  | ❌  | — | SPI SS |

## Tabella PIN — Analogici

| Pin | ADC | Digitale equiv. | Funzione |
|-----|-----|-----------------|---------|
| A0  | ch0 | D54 | Analogico 0-5V, 10-bit |
| A1  | ch1 | D55 | |
| A2  | ch2 | D56 | |
| A3  | ch3 | D57 | |
| A4  | ch4 | D58 | |
| A5  | ch5 | D59 | |
| A6  | ch6 | D60 | |
| A7  | ch7 | D61 | |
| A8  | ch8 | D62 | |
| A9  | ch9 | D63 | |
| A10 | ch10| D64 | |
| A11 | ch11| D65 | |
| A12 | ch12| D66 | |
| A13 | ch13| D67 | |
| A14 | ch14| D68 | |
| A15 | ch15| D69 | |

## Bus e interfacce

### Serial (4 UART hardware)
```cpp
Serial.begin(9600);    // UART0: TX=D1, RX=D0 (USB)
Serial1.begin(9600);   // UART1: TX=D18, RX=D19
Serial2.begin(9600);   // UART2: TX=D16, RX=D17
Serial3.begin(9600);   // UART3: TX=D14, RX=D15
```

### I2C (Wire)
```cpp
#include <Wire.h>
Wire.begin(); // SDA=D20, SCL=D21
```

### SPI
```cpp
#include <SPI.h>
SPI.begin(); // SCK=D52, MISO=D50, MOSI=D51, SS=D53
```

### PWM (15 pin, ~490Hz)
```cpp
analogWrite(3, 128);  // pin PWM: 2-13, 44, 45, 46
```

### ADC (16 canali, 10-bit)
```cpp
int val = analogRead(A0); // 0-1023, 0-5V
```

### EEPROM (4 KB)
```cpp
#include <EEPROM.h>
EEPROM.write(addr, val); // addr 0-4095
```

## Interrupt hardware

| Pin | Interrupt | Tipo |
|-----|-----------|------|
| D2  | INT4 | RISING, FALLING, CHANGE, LOW |
| D3  | INT5 | RISING, FALLING, CHANGE, LOW |
| D18 | INT3 | RISING, FALLING, CHANGE, LOW |
| D19 | INT2 | RISING, FALLING, CHANGE, LOW |
| D20 | INT1 | RISING, FALLING, CHANGE, LOW |
| D21 | INT0 | RISING, FALLING, CHANGE, LOW |

```cpp
attachInterrupt(digitalPinToInterrupt(2), myISR, FALLING);
```

**PCINT** (Pin Change Interrupt): disponibili su tutti i pin, meno precisi.

## Quando usare Mega vs Uno

| Criterio | Uno | Mega |
|---------|-----|------|
| RAM necessaria > 2KB | ❌ | ✅ |
| Più di 2 UART | ❌ | ✅ (4 UART) |
| Più di 6 PWM | ❌ | ✅ (15 PWM) |
| Più di 14 digital pin | ❌ | ✅ (54 pin) |
| Più di 6 analogici | ❌ | ✅ (16 analogici) |
| Sketch semplice/piccolo | ✅ | ok |
| Flash > 32KB | ❌ | ✅ (256KB) |

## Quirks e avvertenze

1. **D0/D1**: condivisi con USB — evitare durante programmazione
2. **Tensione 5V**: non collegare direttamente a device 3.3V (ESP32, sensori 3.3V)
3. **SPI pin diversi da Uno**: MOSI=D51, MISO=D50, SCK=D52, SS=D53 (NON D11/D12/D13 come Uno)
4. **I2C pin diversi da Uno**: SDA=D20, SCL=D21 (NON A4/A5 come Uno)
5. **F() macro**: sempre usarla per stringhe costanti anche qui (8KB RAM si esaurisce con array grandi)

## Sketch minimo
```cpp
void setup() {
  Serial.begin(9600);
  pinMode(13, OUTPUT);
  Serial.println(F("Arduino Mega 2560 pronto"));
  Serial.print(F("Pin D20=SDA, D21=SCL, D51=MOSI, D50=MISO, D52=SCK"));
}

void loop() {
  digitalWrite(13, HIGH);
  delay(500);
  digitalWrite(13, LOW);
  delay(500);
}
```
