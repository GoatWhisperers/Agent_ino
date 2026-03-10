"""
Gestore board Arduino/ESP32 per l'agente.

Funzioni:
  - get(board_id)          → info completa su una board
  - resolve(fqbn_or_alias) → trova la board dal FQBN o alias
  - get_pinout(board_id)   → testo markdown del pinout
  - suggest_pins(board_id, role) → pin consigliato per un ruolo (I2C, SPI, LED...)
  - list_all()             → lista tutte le board nel catalogo
  - fqbn_to_pio(fqbn)      → converte FQBN in PlatformIO board ID
"""

import json
from pathlib import Path

BOARDS_DIR   = Path(__file__).parent
CATALOG_PATH = BOARDS_DIR / "catalog.json"


def _load() -> dict:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)["boards"]


# ── API pubblica ───────────────────────────────────────────────────────────────

def list_all() -> list[str]:
    """Ritorna la lista degli ID board nel catalogo."""
    return list(_load().keys())


def get(board_id: str) -> dict | None:
    """
    Ritorna le info complete di una board dall'ID.
    Ritorna None se non trovata.
    """
    boards = _load()
    return boards.get(board_id)


def resolve(identifier: str) -> dict | None:
    """
    Trova una board da FQBN, alias o ID parziale.
    Esempi: "esp32:esp32:esp32", "uno", "mega", "wroom", "esp8266"
    """
    boards = _load()
    identifier = identifier.lower().strip()

    # Match diretto sull'ID
    if identifier in boards:
        return boards[identifier]

    # Match su FQBN
    for board in boards.values():
        if board.get("fqbn", "").lower() == identifier:
            return board

    # Match su PlatformIO board ID
    for board in boards.values():
        if board.get("pio_board", "").lower() == identifier:
            return board

    # Match su alias
    for board in boards.values():
        for alias in board.get("aliases", []):
            if alias.lower() == identifier:
                return board

    # Match parziale su nome o alias
    for board in boards.values():
        if identifier in board.get("name", "").lower():
            return board
        for alias in board.get("aliases", []):
            if identifier in alias.lower():
                return board

    return None


def get_pinout(board_id: str) -> str:
    """
    Ritorna il contenuto del file markdown del pinout.
    Ritorna stringa vuota se non trovato.
    """
    board = get(board_id) or resolve(board_id)
    if not board:
        return ""
    pinout_rel = board.get("pinout_file", "")
    if not pinout_rel:
        return ""
    pinout_path = BOARDS_DIR / pinout_rel
    if pinout_path.exists():
        return pinout_path.read_text(encoding="utf-8")
    return ""


def suggest_pins(board_id: str, role: str) -> dict:
    """
    Suggerisce i pin per un ruolo specifico.

    role: "i2c", "spi", "uart", "led", "pwm", "adc", "touch", "dac"

    Ritorna dict con i pin consigliati, es:
      {"sda": 21, "scl": 22} per I2C
      {"mosi": 23, "miso": 19, "sck": 18, "ss": 5} per SPI
    """
    board = get(board_id) or resolve(board_id)
    if not board:
        return {}

    pins = board.get("pins", {})
    role = role.lower()

    if role == "i2c":
        return {"sda": pins.get("i2c_sda"), "scl": pins.get("i2c_scl")}
    elif role == "spi":
        return {
            "mosi": pins.get("spi_mosi"),
            "miso": pins.get("spi_miso"),
            "sck":  pins.get("spi_sck"),
            "ss":   pins.get("spi_ss"),
        }
    elif role == "uart" or role == "serial":
        result = {"tx": pins.get("uart0_tx"), "rx": pins.get("uart0_rx")}
        if pins.get("uart1_tx"):
            result["uart1"] = {"tx": pins["uart1_tx"], "rx": pins["uart1_rx"]}
        if pins.get("uart2_tx"):
            result["uart2"] = {"tx": pins["uart2_tx"], "rx": pins["uart2_rx"]}
        if pins.get("uart3_tx"):
            result["uart3"] = {"tx": pins["uart3_tx"], "rx": pins["uart3_rx"]}
        return result
    elif role == "led":
        return {
            "pin": pins.get("led_builtin"),
            "active_low": pins.get("led_builtin_active_low", False),
        }
    elif role == "pwm":
        pwm_list = pins.get("pwm_pins", [])
        if not pwm_list and pins.get("pwm_any_gpio"):
            return {"note": "Qualunque GPIO supporta PWM (LEDC)", "suggested": [3, 5, 9, 10]}
        return {"pins": pwm_list}
    elif role == "adc":
        if pins.get("adc1_pins"):
            return {
                "adc1": pins["adc1_pins"],
                "adc2": pins.get("adc2_pins", []),
                "note": "Preferire ADC1 se WiFi è attivo",
            }
        return {"pins": pins.get("analog_pins", []), "bits": pins.get("adc_bits", 10)}
    elif role == "touch":
        return {"pins": pins.get("touch_pins", [])}
    elif role == "dac":
        result = {}
        if pins.get("dac1"):
            result["dac1"] = pins["dac1"]
        if pins.get("dac2"):
            result["dac2"] = pins["dac2"]
        return result
    return {}


def fqbn_to_pio(fqbn: str) -> str | None:
    """Converte un arduino FQBN nel PlatformIO board ID."""
    board = resolve(fqbn)
    if board:
        return board.get("pio_board")
    return None


def get_notes(board_id: str) -> list[str]:
    """Ritorna le note/avvertenze della board."""
    board = get(board_id) or resolve(board_id)
    if not board:
        return []
    return board.get("notes", [])


def is_esp32_family(board_id: str) -> bool:
    """True se la board è ESP32/ESP8266 (usa Raspberry per programmazione)."""
    board = get(board_id) or resolve(board_id)
    if not board:
        return False
    return board.get("programmer") == "raspberry_pi"


def is_avr(board_id: str) -> bool:
    """True se la board è Arduino AVR (usa USB locale per programmazione)."""
    board = get(board_id) or resolve(board_id)
    if not board:
        return False
    return board.get("programmer") == "local_usb"


def print_summary():
    """Stampa un sommario leggibile del catalogo board."""
    boards = _load()
    print(f"\n{'='*65}")
    print(f"{'BOARD':20} {'MCU':28} {'RAM':8} {'FLASH':8} {'CONN'}")
    print(f"{'='*65}")
    for bid, b in boards.items():
        conn = ", ".join(b.get("connectivity", []) or ["—"])
        print(f"{bid:20} {b['mcu'][:28]:28} {b['ram_kb']:4}KB  {b['flash_kb']:4}KB  {conn}")

    print(f"\n{'FQBN':45} {'PIO Board ID'}")
    print("-" * 65)
    for bid, b in boards.items():
        print(f"  {b['fqbn']:43} {b['pio_board']}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print_summary()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "list":
        print_summary()

    elif cmd == "info" and len(sys.argv) > 2:
        board = resolve(" ".join(sys.argv[2:]))
        if board:
            print(json.dumps(board, indent=2, ensure_ascii=False))
        else:
            print(f"Board non trovata: {sys.argv[2:]}")

    elif cmd == "pinout" and len(sys.argv) > 2:
        text = get_pinout(sys.argv[2])
        print(text if text else f"Pinout non trovato per {sys.argv[2]}")

    elif cmd == "pins" and len(sys.argv) > 3:
        board_id = sys.argv[2]
        role = sys.argv[3]
        result = suggest_pins(board_id, role)
        print(f"{board_id} — pin per {role}: {result}")

    elif cmd == "notes" and len(sys.argv) > 2:
        notes = get_notes(sys.argv[2])
        print(f"\nNote per {sys.argv[2]}:")
        for n in notes:
            print(f"  ⚠ {n}")

    else:
        print("Uso: python board_manager.py [list | info <board> | pinout <board> | pins <board> <role> | notes <board>]")
