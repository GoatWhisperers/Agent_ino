"""
Wrapper around arduino-cli for compiling Arduino sketches.

arduino-cli binary path: /home/lele/codex-openai/programmatore_di_arduini/bin/arduino-cli
"""

import os
import re
import subprocess
import tempfile
from typing import Optional

ARDUINO_CLI = "/home/lele/codex-openai/programmatore_di_arduini/bin/arduino-cli"

# Regex per righe di errore/warning prodotte da arduino-cli / avr-gcc
# Formato: /path/to/file.ino:riga:col: error: messaggio
_DIAG_RE = re.compile(
    r"^(?P<file>[^:]+\.(?:ino|cpp|c|h)):(?P<line>\d+):(?P<col>\d+):\s*(?P<type>fatal error|error|warning|note):\s*(?P<message>.+)$"
)

# Formato senza colonna: file:riga: error: messaggio
_DIAG_NO_COL_RE = re.compile(
    r"^(?P<file>[^:]+\.(?:ino|cpp|c|h)):(?P<line>\d+):\s*(?P<type>fatal error|error|warning|note):\s*(?P<message>.+)$"
)


def _parse_diagnostics(text: str) -> tuple[list[dict], list[dict]]:
    """
    Parse arduino-cli / compiler output and return (errors, warnings).

    Each error dict: {"file": str, "line": int, "col": int, "type": str, "message": str}
    Each warning dict: {"file": str, "line": int, "message": str}
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        m = _DIAG_RE.match(line) or _DIAG_NO_COL_RE.match(line)
        if not m:
            continue

        diag_type = m.group("type")
        file_name = m.group("file")
        line_no = int(m.group("line"))
        col_no = int(m.group("col")) if "col" in m.groupdict() and m.group("col") else 0
        message = m.group("message")

        if diag_type in ("error", "fatal error"):
            errors.append({
                "file": file_name,
                "line": line_no,
                "col": col_no,
                "type": "error",
                "message": message,
            })
        elif diag_type == "warning":
            warnings.append({
                "file": file_name,
                "line": line_no,
                "message": message,
            })
        # "note" viene ignorato (non errore né warning principale)

    return errors, warnings


# Mappatura: include errato → include corretto (errori comuni di M40/Gemma)
_INCLUDE_FIXES = {
    "#include <SSD1306.h>":          "#include <Adafruit_SSD1306.h>",
    "#include <Adafruit_SSD1306.h>": "#include <Adafruit_SSD1306.h>",  # già corretto
    "#include <GFX.h>":              "#include <Adafruit_GFX.h>",
    "#include <U8glib.h>":           "#include <U8g2lib.h>",
    "#include <DHT.h>":              "#include <DHT.h>",  # già corretto (Adafruit)
}


def fix_italian_pseudocode(code: str) -> str:
    """Converte righe di pseudocodice italiano senza '//' in commenti C++ validi.

    M40 a volte lascia testo descrittivo come codice eseguibile invece di commentarlo.
    Pattern tipici: 'Solo su prede. dx=dy=0.', 'Trova la preda più vicina.', ecc.
    Questa funzione li converte in commenti prima della compilazione.
    """
    import re
    fixed_lines = []
    for line in code.splitlines():
        stripped = line.lstrip()
        # Salta righe già valide: vuote, commenti, preprocessore, parentesi, keywords C++
        if (not stripped
                or stripped.startswith("//")
                or stripped.startswith("/*")
                or stripped.startswith("#")
                or stripped.startswith("{")
                or stripped.startswith("}")
                or stripped.startswith("*")):
            fixed_lines.append(line)
            continue
        # In C++ una riga non può terminare con '.' (a meno che sia dentro una stringa).
        # Se termina con '.' è pseudocodice italiano → commentarla.
        # Eccezione: righe che iniziano con '"' (stringhe letterali) o sono float literals.
        ends_with_dot = stripped.rstrip().endswith(".")
        is_string_literal = stripped.startswith('"') or stripped.startswith("'")
        is_float_literal = re.match(r"^[\d\s\+\-\*\/\.]+$", stripped)
        if ends_with_dot and not is_string_literal and not is_float_literal:
            indent = line[: len(line) - len(stripped)]
            # Commenta la riga pseudocodice
            fixed_lines.append(f"{indent}// {stripped}")
            # Estrai dichiarazioni implicite da assegnamenti concatenati tipo cx=cy=0; cnt=0.
            # Cattura tutti gli identificatori a sinistra di "=...0"
            # Es: "dx=dy=0; cnt=0." → vars: [dx, dy, cnt]
            all_vars = re.findall(r"\b([a-z_][a-z_0-9]*)\s*=", stripped.lower())
            # Rimuovi variabili che sono già parametri della funzione corrente
            # (cerca la firma della funzione nelle righe precedenti)
            func_params: set[str] = set()
            for prev in reversed(fixed_lines[-20:]):
                m = re.search(r"\w+\s*\([^)]*\)\s*\{?\s*$", prev)
                if m:
                    param_names = re.findall(r"\b([a-z_][a-z_0-9]*)\s*[,)]", prev)
                    func_params = set(param_names)
                    break
            decls = []
            seen: set[str] = set()
            for var in all_vars:
                if var in seen or var in func_params:
                    continue
                seen.add(var)
                if var in ("cnt", "n", "i", "j", "k"):
                    decls.append(f"int {var} = 0;")
                elif var in ("cx", "cy", "dx", "dy", "fx", "fy", "ax", "ay", "sx", "sy",
                             "d", "spd", "angle", "minDist"):
                    decls.append(f"float {var} = 0;")
            if decls:
                fixed_lines.append(f"{indent}{' '.join(decls)}")
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)


def fix_m40_runtime_bugs(code: str) -> str:
    """Corregge bug ricorrenti nel codice generato da M40 — rilevati empiricamente.

    Applicato PRIMA della compilazione, indipendentemente dagli errori.
    """
    # Bug 1: timer millis() dichiarati come int invece di unsigned long
    # → int lastSerialTime / int spawnTimer ecc. causano overflow dopo 32s
    for timer_var in ("lastSerialTime", "serialTimer", "spawnTimer",
                      "respawnTimer", "catchTimer", "blinkTimer",
                      "prevMillis", "lastMillis", "timerMillis"):
        # Sostituisce solo le dichiarazioni globali/locali, non i parametri funzione
        code = re.sub(
            rf"\bint\s+({timer_var})\s*=\s*0\s*;",
            r"unsigned long \1 = 0;",
            code,
        )
    # Bug 2: fillRect/drawRect senza colore (5° parametro obbligatorio su Adafruit_GFX)
    # → no matching function for call to 'Adafruit_SSD1306::fillRect(int, int, int, int)'
    def _add_color_param(m):
        return f"{m.group(1)}({m.group(2)}, SSD1306_WHITE)"
    code = re.sub(
        r"(display\.(fillRect|drawRect))\((\s*[^,)]+,\s*[^,)]+,\s*[^,)]+,\s*[^,)]+)\)",
        lambda m: f"{m.group(1)}({m.group(3)}, SSD1306_WHITE)",
        code,
    )

    # Bug 3: Serial.println/print usato ma Serial.begin() mancante in setup()
    # → serial output completamente silenzioso → serial-first evaluation fallisce
    if re.search(r"\bSerial\.(print|println|write)\b", code):
        if not re.search(r"\bSerial\.begin\s*\(", code):
            # Inietta Serial.begin(115200) all'inizio di setup()
            code = re.sub(
                r"(void\s+setup\s*\(\s*\)\s*\{)",
                r"\1\n  Serial.begin(115200);",
                code,
                count=1,
            )
    return code


def fix_known_includes(code: str) -> str:
    """Sostituisce include noti errati con quelli corretti prima di compilare."""
    # Fix pseudocodice italiano prima degli altri fix
    code = fix_italian_pseudocode(code)
    # Fix bug runtime M40 ricorrenti
    code = fix_m40_runtime_bugs(code)
    for wrong, correct in _INCLUDE_FIXES.items():
        if wrong != correct:
            code = code.replace(wrong, correct)
    # SSD1306 è MONOCROMATICO — sostituisce colori inesistenti con WHITE
    for bad_color in ("SSD1306_GREEN", "SSD1306_RED", "SSD1306_BLUE",
                      "SSD1306_YELLOW", "SSD1306_CYAN", "SSD1306_MAGENTA",
                      "SSD1306_ORANGE", "SSD1306_BLACK"):
        code = code.replace(bad_color, "SSD1306_WHITE")
    # Adafruit_GFX::WHITE / Adafruit_GFX::BLACK ecc. — invalid C++ (WHITE è un #define,
    # non un membro della classe). Sostituisci con le costanti SSD1306_ equivalenti.
    code = re.sub(r"Adafruit_GFX\s*::\s*WHITE",   "SSD1306_WHITE",   code)
    code = re.sub(r"Adafruit_GFX\s*::\s*BLACK",   "SSD1306_BLACK",   code)
    code = re.sub(r"Adafruit_GFX\s*::\s*INVERSE", "SSD1306_INVERSE", code)
    # Proactive M40 pattern fixes (applicati SEMPRE, non solo su errori compilazione):
    # 1. drawCircle/fillCircle con float — aggiunge cast (int) e rimuove 5° argomento
    code = _fix_drawCircle_float(code)
    # 2. dist() chiamato senza essere definito — aggiunge helper globale
    if re.search(r"\bdist\s*\(", code) and "float dist(" not in code:
        code = _fix_dist_function(code)
    # 3. uint8_t* grid (1D pointer) usato come 2D array — converte a uint8_t grid[][16]
    # M40 scrive uint8_t* grid in funzioni che poi fanno grid[y][x] — non compila
    code = _fix_uint8_grid_pointer(code)
    return code


# ── Metodi validi di Adafruit_SSD1306 / Adafruit_GFX ─────────────────────────
_SSD1306_METHODS = {
    "begin", "display", "clearDisplay", "drawPixel", "drawLine", "drawRect",
    "fillRect", "drawCircle", "fillCircle", "drawTriangle", "fillTriangle",
    "drawRoundRect", "fillRoundRect", "drawBitmap", "setCursor", "setTextColor",
    "setTextSize", "setTextWrap", "print", "println", "write", "getTextBounds",
    "setRotation", "invertDisplay", "dim", "startscrollright", "startscrollleft",
    "startscrolldiagright", "startscrolldiagleft", "stopscroll",
    "width", "height", "fillScreen", "setFont", "setContrast", "oled_command",
}


def _fix_display_userfunc_calls(code: str) -> str:
    """
    Rimuove 'display.' da funzioni che NON sono metodi di Adafruit_SSD1306.
    Es: display.drawTextCentrato() → drawTextCentrato()
    """
    def _replace(m):
        method = m.group(1)
        if method not in _SSD1306_METHODS:
            return method + "("   # rimuovi "display."
        return m.group(0)         # lascia invariato

    return re.sub(r"\bdisplay\.(\w+)\s*\(", _replace, code)


def _fix_getTextBounds_call(code: str) -> str:
    """
    Corregge chiamate errate a getTextBounds:
    - display.textWidth(text, &w, &h)  → getTextBounds a 7 arg con tipi corretti
    - getTextBounds a 5 arg            → aggiunge i 2 parametri out x1,y1 mancanti
    - dichiarazioni int vicine         → int16_t/uint16_t corretti
    """
    # Fix 1: display.textWidth(expr, &varW, &varH) → non esiste, replace con getTextBounds
    m = re.search(r"display\.textWidth\s*\(([^,]+),\s*&(\w+),\s*&(\w+)\)", code)
    if m:
        expr, varW, varH = m.group(1).strip(), m.group(2), m.group(3)
        # Aggiusta dichiarazione delle variabili (int varW, varH → tipi corretti)
        code = re.sub(
            r"\bint\b(\s+)" + varW + r"\s*,\s*" + varH + r"\s*;",
            f"int16_t _gbx1, _gby1; uint16_t {varW}, {varH};",
            code,
        )
        code = re.sub(
            r"\bint\b(\s+)" + varH + r"\s*,\s*" + varW + r"\s*;",
            f"int16_t _gbx1, _gby1; uint16_t {varH}, {varW};",
            code,
        )
        # Replace la chiamata textWidth con getTextBounds 7-arg
        code = re.sub(
            r"display\.textWidth\s*\([^)]+\)",
            f"display.getTextBounds({expr}, 0, 0, &_gbx1, &_gby1, &{varW}, &{varH})",
            code,
        )

    # Fix 2: getTextBounds a 5 arg (mancano x1,y1 out)
    # Pattern: display.getTextBounds(text, x, y, &w, &h) → 7 arg
    def _fix_5arg(m2):
        text_arg = m2.group(1)
        x_arg    = m2.group(2)
        y_arg    = m2.group(3)
        varW     = m2.group(4)
        varH     = m2.group(5)
        return f"display.getTextBounds({text_arg}, {x_arg}, {y_arg}, &_gbx1, &_gby1, &{varW}, &{varH})"

    code = re.sub(
        r"display\.getTextBounds\s*\(\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*&(\w+),\s*&(\w+)\s*\)",
        _fix_5arg,
        code,
    )

    # Fix 3: assicura che _gbx1, _gby1 siano dichiarati se si usa getTextBounds
    if "display.getTextBounds" in code and "_gbx1" in code and "int16_t _gbx1" not in code:
        # Inserisce dichiarazione prima della prima chiamata
        code = re.sub(
            r"(display\.getTextBounds\s*\()",
            "int16_t _gbx1, _gby1;\r\n  \\1",
            code,
            count=1,
        )

    return code


def _fix_dist_function(code: str) -> str:
    """Aggiunge helper dist(x1,y1,x2,y2) se manca — M40 lo chiama ma non lo definisce."""
    helper = (
        "\n// Helper: distanza euclidea (M40 usa dist() che non esiste in Arduino)\n"
        "float dist(float x1, float y1, float x2, float y2) {\n"
        "  return sqrt(pow(x2 - x1, 2) + pow(y2 - y1, 2));\n"
        "}\n"
    )
    # Inserisce dopo gli #include / #define iniziali, prima della prima funzione/struct
    if "float dist(" in code or "inline float dist(" in code:
        return code  # già definita
    # Trova l'ultima riga #include / #define (non commenti //
    # per evitare di inserire dentro le funzioni)
    insert_line_end = 0
    for m in re.finditer(r"^(#include|#define)\b", code, re.MULTILINE):
        eol = code.find("\n", m.start())
        if eol > insert_line_end:
            insert_line_end = eol
    if insert_line_end == 0:
        # Nessun include/define trovato — inserisce all'inizio
        return helper + "\n" + code
    return code[:insert_line_end + 1] + helper + code[insert_line_end + 1:]


def _fix_setupPhysics_call(code: str) -> str:
    """Rimuove chiamata a setupPhysics() se non definita — M40 la inventa a volte."""
    code = re.sub(r"^\s*setupPhysics\s*\(\s*\)\s*;\s*\n", "", code, flags=re.MULTILINE)
    return code


def _fix_drawCircle_float(code: str) -> str:
    """
    Aggiunge cast (int) agli argomenti float di drawCircle/fillCircle/drawCircle.
    Errore tipico: drawCircle(predator.x, predator.y, 4, SSD1306_WHITE, 0)
      → drawCircle(float&, float&, int, int, int) — no match
    Fix: cast x,y a int; rimuove 5° argomento (fillCircle ha 4 arg, non 5).
    """
    # Caso 1: drawCircle(floatX, floatY, radius, color, extra) — 5 args
    # Rimuove il 5° argomento e casta x,y
    def _replace_5arg(m):
        fname = m.group(1)
        x_arg = m.group(2).strip()
        y_arg = m.group(3).strip()
        r_arg = m.group(4).strip()
        color = m.group(5).strip()
        # Cast x,y a int se sembrano float (contengono '.', o sono variabili non intere)
        x_cast = f"(int)({x_arg})" if "." not in x_arg else f"(int)({x_arg})"
        y_cast = f"(int)({y_arg})" if "." not in y_arg else f"(int)({y_arg})"
        return f"display.{fname}({x_cast}, {y_cast}, {r_arg}, {color})"

    code = re.sub(
        r"display\.(drawCircle|fillCircle)\s*\(\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*\d+\s*\)",
        _replace_5arg,
        code,
    )

    # Caso 2: drawCircle(floatX, floatY, radius, color) — 4 args ma x,y sono float vars
    def _replace_4arg_float(m):
        fname = m.group(1)
        x_arg = m.group(2).strip()
        y_arg = m.group(3).strip()
        r_arg = m.group(4).strip()
        color = m.group(5).strip()
        return f"display.{fname}((int)({x_arg}), (int)({y_arg}), {r_arg}, {color})"

    # Sostituisce solo se x_arg sembra una variabile float (es. predator.x, prey[i].x)
    code = re.sub(
        r"display\.(drawCircle|fillCircle)\s*\(\s*([a-z_]\w*(?:\.\w+|\[\w+\]\.\w+)?),\s*([a-z_]\w*(?:\.\w+|\[\w+\]\.\w+)?),\s*([^,]+),\s*(SSD1306_WHITE|SSD1306_BLACK|WHITE|BLACK)\s*\)",
        _replace_4arg_float,
        code,
    )
    return code


def _fix_setPixel_to_drawPixel(code: str) -> str:
    """Fix: M40 usa .setPixel() che non esiste su Adafruit_SSD1306 — il metodo corretto è drawPixel()."""
    return re.sub(r"\bdisplay\.setPixel\s*\(", "display.drawPixel(", code)


def _fix_drawString_to_setCursor_print(code: str) -> str:
    """Fix: M40 usa display.drawString(text, x, y) che non esiste in Adafruit_SSD1306.
    Corretto: display.setCursor(x, y); display.print(text);
    Pattern:  display.drawString(testo, x, y)  →  display.setCursor(x, y); display.print(testo)
    """
    # Cerca chiamate display.drawString(arg0, arg1, arg2) e le converte
    def _replace_drawstring(m):
        args = m.group(1)
        # Cerca di separare i 3 argomenti (text, x, y) tenendo conto di parentesi bilanciate
        depth = 0
        parts = []
        current = []
        for ch in args:
            if ch == ',' and depth == 0:
                parts.append(''.join(current).strip())
                current = []
            else:
                if ch in '([': depth += 1
                elif ch in ')]': depth -= 1
                current.append(ch)
        parts.append(''.join(current).strip())
        if len(parts) == 3:
            text_arg, x_arg, y_arg = parts
            return f"display.setCursor({x_arg}, {y_arg}); display.print({text_arg})"
        # fallback: se non riesce a parsare, almeno rimuove la chiamata illegale
        return f"/* drawString non esiste: usare setCursor+print */ display.print({args})"
    code = re.sub(r"\bdisplay\.drawString\s*\(([^;]+)\)", _replace_drawstring, code)
    return code


def _fix_drawChar_wrong_order(code: str) -> str:
    """Fix: M40 usa display.drawChar(char, 0, x, y) con ordine argomenti sbagliato.
    Adafruit_GFX::drawChar firma: drawChar(x, y, c, color, bg, size)
    Converte il loop drawChar in setCursor+print più semplice."""
    # Se c'è un for loop su drawChar per stampare una stringa, lo converte
    # Pattern: for (... i ...) { display.drawChar(str[i], 0, x + i * 8, y); }
    # → display.setCursor(x, y); display.print(str);
    # Approccio semplice: sostituisce display.drawChar(... [i] ...) con nota
    if "display.drawChar" not in code:
        return code
    # Cerca il pattern del loop di stampa carattere per carattere
    code = re.sub(
        r"for\s*\([^)]+\)\s*\{\s*display\.drawChar\s*\([^)]+\[i\][^)]*\)\s*;\s*\}",
        lambda m: "// drawChar loop rimosso — usare setCursor+print",
        code
    )
    return code


def _fix_drawHLine_to_drawFastHLine(code: str) -> str:
    """Fix: M40 usa drawHLine()/drawVLine() che non esistono in Adafruit_GFX.
    Corretto: drawFastHLine(x, y, w, color) e drawFastVLine(x, y, h, color)."""
    code = re.sub(r"\bdisplay\.drawHLine\s*\(", "display.drawFastHLine(", code)
    code = re.sub(r"\bdisplay\.drawVLine\s*\(", "display.drawFastVLine(", code)
    return code


def _fix_uint8_grid_pointer(code: str) -> str:
    """
    Fix: M40 scrive uint8_t* grid come parametro ma poi usa grid[y][x] (2D array access).
    Converte le firme da uint8_t* grid a uint8_t grid[][16] per array bit-packed 128x64.
    Applica anche alle forward declarations.

    Esempio:
      bool getCell(uint8_t* grid, int x, int y)  →  bool getCell(uint8_t grid[][16], int x, int y)
    """
    # Converti solo se c'è accesso 2D nell'implementazione (grid[y][x])
    # Pattern: (tipo_ritorno) nome_funz(... uint8_t* grid ...) { ... grid[y][x] ... }
    if "uint8_t* grid" not in code:
        return code

    # Verifica che ci sia accesso 2D (grid[...][...]) per evitare false conversioni
    if not re.search(r"\bgrid\s*\[\s*\w+\s*\]\s*\[\s*\w+\s*\]", code):
        return code

    # Sostituisce uint8_t* grid con uint8_t grid[][16] nelle firme di funzione
    # Sia nelle definizioni che nelle forward declarations
    code = re.sub(r"\buint8_t\s*\*\s*grid\b", "uint8_t grid[][16]", code)
    return code


# Mappa: pattern nel messaggio di errore → funzione di fix
_API_ERROR_FIXES = [
    ("has no member named 'textWidth'",          _fix_getTextBounds_call),
    ("no matching function for call to 'Adafruit_SSD1306::getTextBounds", _fix_getTextBounds_call),
    ("has no member named '",                     _fix_display_userfunc_calls),
    ("'dist' was not declared",                   _fix_dist_function),
    ("'setupPhysics' was not declared",           _fix_setupPhysics_call),
    ("no matching function for call to 'Adafruit_SSD1306::drawCircle", _fix_drawCircle_float),
    ("no matching function for call to 'Adafruit_SSD1306::fillCircle", _fix_drawCircle_float),
    ("cannot convert 'uint8_t (*)[",                                   _fix_uint8_grid_pointer),
    ("has no member named 'setPixel'",                                 _fix_setPixel_to_drawPixel),
    ("'drawHLine' was not declared",                                   _fix_drawHLine_to_drawFastHLine),
    ("'drawVLine' was not declared",                                   _fix_drawHLine_to_drawFastHLine),
    ("has no member named 'drawString'",                               _fix_drawString_to_setCursor_print),
    ("has no member named 'drawString'",                               _fix_drawChar_wrong_order),
]


def fix_known_api_errors(code: str, errors: list[dict]) -> str:
    """
    Applica fix hardcoded basandosi sui messaggi di errore del compilatore.
    Chiamare PRIMA di passare il codice al patcher LLM e PRIMA di compilare.

    errors: lista di dict {"message": str, ...} da compile_sketch()
    Ritorna il codice con i fix applicati.
    """
    applied = set()
    for err in errors:
        msg = err.get("message", "")
        for pattern, fix_fn in _API_ERROR_FIXES:
            if pattern in msg and fix_fn not in applied:
                code = fix_fn(code)
                applied.add(fix_fn)
    return code


# Librerie built-in del framework Arduino/ESP32 (non appaiono in arduino-cli lib list)
_BUILTIN_LIBS = {
    "wire", "spi", "eeprom", "sd", "servo", "software serial", "softwareserial",
    "arduinoota", "asyncudp", "ble", "bluetoothserial", "dnsserver", "esp32",
    "espdns", "espm dns", "espmacds", "espmDNS", "ethernet", "eth", "ffat", "fs",
    "httpclient", "httpupdate", "httpupdateserver", "i2s", "insights", "littlefs",
    "netbios", "preferences", "rainmaker", "sd mmc", "simpleble", "spiffs",
    "ticker", "update", "usb", "webserver", "wifi", "wificlientsecure", "wifiprov",
}

# Alias nomi libreria usati nei prompt ↔ nomi reali del registry Arduino.
_LIB_ALIASES = {
    "dhtesp": {"dht sensor library for espx", "dht sensor library"},
}


def check_libraries(library_names: list[str]) -> dict:
    """
    Verifica che le librerie Arduino siano installate in arduino-cli.

    library_names: lista di nomi librerie da controllare (es. ["Adafruit SSD1306"])
    Ritorna: {"all_ok": bool, "missing": list[str], "installed": list[str]}
    """
    if not library_names:
        return {"all_ok": True, "missing": [], "installed": []}

    try:
        r = subprocess.run(
            [ARDUINO_CLI, "lib", "list", "--format", "json"],
            capture_output=True, text=True, timeout=30
        )
        data = __import__("json").loads(r.stdout or "{}")
        # data è {"installed_libraries": [{"library": {"name": "...", ...}}, ...]}
        items = data.get("installed_libraries", []) if isinstance(data, dict) else data
        installed_names = set()
        for item in items:
            lib = item.get("library", {})
            if lib.get("name"):
                installed_names.add(lib["name"].lower())
            if lib.get("real_name"):
                installed_names.add(lib["real_name"].lower())
    except Exception:
        # Se arduino-cli non risponde, considera tutto installato (non bloccare)
        return {"all_ok": True, "missing": [], "installed": library_names}

    def _normalize(s: str) -> str:
        return s.lower().replace("_", " ").replace("-", " ")

    normalized_installed = {_normalize(n) for n in installed_names}

    missing = []
    installed = []
    for name in library_names:
        name_norm = _normalize(name)
        # built-in: sempre disponibile
        if name_norm in _BUILTIN_LIBS:
            installed.append(name)
            continue
        # ricerca flessibile: match esatto o sottostringa normalizzata
        found = any(name_norm in n or n in name_norm for n in normalized_installed)
        if not found and name_norm in _LIB_ALIASES:
            found = any(
                any(alias in n or n in alias for n in normalized_installed)
                for alias in _LIB_ALIASES[name_norm]
            )
        if found:
            installed.append(name)
        else:
            missing.append(name)

    return {"all_ok": len(missing) == 0, "missing": missing, "installed": installed}


def _find_hex(build_dir: str) -> Optional[str]:
    """Return the path of the first .hex file found inside build_dir, or None."""
    for root, _dirs, files in os.walk(build_dir):
        for fname in files:
            if fname.endswith(".hex"):
                return os.path.join(root, fname)
    return None


def compile_sketch(sketch_path: str, fqbn: str = "arduino:avr:uno") -> dict:
    """
    Compile an Arduino sketch using arduino-cli.

    Parameters
    ----------
    sketch_path : str
        Absolute path to the sketch directory (must contain a .ino file with
        the same name as the directory).
    fqbn : str
        Fully Qualified Board Name, e.g. "arduino:avr:uno".

    Returns
    -------
    dict with keys:
        success      : bool
        binary_path  : str | None   – path to the .hex file if compilation succeeded
        errors       : list[dict]   – structured error list
        warnings     : list[dict]   – structured warning list
        raw_stdout   : str
        raw_stderr   : str
    """
    sketch_path = os.path.abspath(sketch_path)

    with tempfile.TemporaryDirectory(prefix="arduino_build_") as build_dir:
        cmd = [
            ARDUINO_CLI,
            "compile",
            "--fqbn", fqbn,
            "--output-dir", build_dir,
            sketch_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            return {
                "success": False,
                "binary_path": None,
                "errors": [{"file": "", "line": 0, "col": 0, "type": "error",
                            "message": f"arduino-cli non trovato: {ARDUINO_CLI}"}],
                "warnings": [],
                "raw_stdout": "",
                "raw_stderr": f"FileNotFoundError: {ARDUINO_CLI}",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "binary_path": None,
                "errors": [{"file": "", "line": 0, "col": 0, "type": "error",
                            "message": "Timeout durante la compilazione (>120s)"}],
                "warnings": [],
                "raw_stdout": "",
                "raw_stderr": "TimeoutExpired",
            }

        stdout = result.stdout
        stderr = result.stderr
        success = result.returncode == 0

        # Parsa sia stdout che stderr (arduino-cli mescola i messaggi)
        combined = stdout + "\n" + stderr
        errors, warnings = _parse_diagnostics(combined)

        # Cerca il .hex nella dir di output temporanea — se il processo è
        # terminato con successo il file è già stato scritto.
        binary_path: Optional[str] = None
        if success:
            binary_path = _find_hex(build_dir)
            # Sposta il hex in una posizione stabile accanto allo sketch
            if binary_path:
                stable_hex = os.path.join(sketch_path, os.path.basename(binary_path))
                import shutil
                shutil.copy2(binary_path, stable_hex)
                binary_path = stable_hex

        return {
            "success": success,
            "binary_path": binary_path,
            "errors": errors,
            "warnings": warnings,
            "raw_stdout": stdout,
            "raw_stderr": stderr,
        }
