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


def fix_known_includes(code: str) -> str:
    """Sostituisce include noti errati con quelli corretti prima di compilare."""
    for wrong, correct in _INCLUDE_FIXES.items():
        if wrong != correct:
            code = code.replace(wrong, correct)
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
