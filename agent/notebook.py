"""
Taccuino operativo per task Arduino.

MI50 scrive il piano iniziale (globals + lista funzioni con dipendenze).
M40 riceve solo la slice rilevante — una funzione alla volta.

Struttura funzione:
    nome        : nome C++ (es. "setup", "readTemperature")
    firma       : firma completa (es. "float readTemperature()")
    compito     : descrizione di cosa fa
    dipende_da  : lista nomi funzioni che questa usa
    stato       : pending | generating | done | error
    codice      : corpo completo scritto da M40 (firma + { ... })

Flusso:
    nb = Notebook(task, board)
    nb.set_funzioni(globals_hint, funzioni)   # da Orchestrator
    for func in nb.funzioni_ordinate():
        ctx = nb.context_for_function(func['nome'], globals_code, funzioni_già_scritte)
        codice = M40.generate(ctx)
        nb.update_funzione(func['nome'], 'done', codice)
    sketch = nb.assemble()                    # .ino finale
"""

import json
from datetime import datetime
from pathlib import Path


class Notebook:
    def __init__(self, task: str, board: str):
        self.task = task
        self.board = board
        self.created_at = datetime.utcnow().isoformat()
        # Piano ad alto livello (da Orchestrator fase 1)
        self.piano: list[str] = []
        self.dipendenze: list[str] = []
        self.note_tecniche: list[str] = []
        # Funzioni (da Orchestrator fase 1b)
        self.globals_hint: str = ""          # suggerimento includes/defines per M40
        self.funzioni: list[dict] = []       # [{nome, firma, compito, dipende_da, stato, codice}]
        self.globals_code: str = ""          # scritto da M40
        # Stato generale
        self.stato = "planning"
        self.errori_visti: list[dict] = []
        self.log_fasi: list[dict] = []

    # ── Setup piano ───────────────────────────────────────────────────────────

    def set_plan(self, piano: list[str], dipendenze: list[str] = None,
                 note_tecniche: list[str] = None):
        """Piano ad alto livello (compatibilità con vecchio flusso)."""
        self.piano = piano
        self.dipendenze = dipendenze or []
        self.note_tecniche = note_tecniche or []

    def set_funzioni(self, globals_hint: str, funzioni: list[dict]):
        """
        Imposta la lista di funzioni da generare.
        funzioni: [{"nome": str, "firma": str, "compito": str, "dipende_da": [str]}]
        """
        self.globals_hint = globals_hint
        self.funzioni = [
            {
                "nome": f["nome"],
                "firma": f["firma"],
                "compito": f["compito"],
                "dipende_da": f.get("dipende_da", []),
                "stato": "pending",
                "codice": "",
            }
            for f in funzioni
        ]

    # ── Navigazione funzioni ──────────────────────────────────────────────────

    def funzioni_ordinate(self) -> list[dict]:
        """
        Ritorna le funzioni in ordine di dipendenza (topological sort).
        globals è sempre primo, loop() sempre ultimo.
        """
        if not self.funzioni:
            return []

        ordered = []
        remaining = list(self.funzioni)
        done_nomi = {"__globals__"}

        # Metti setup() prima di loop() — convenzione Arduino
        priority = {"setup": 0, "loop": 999}

        max_iter = len(remaining) * 2
        i = 0
        while remaining and i < max_iter:
            i += 1
            for f in remaining[:]:
                if all(dep in done_nomi for dep in f["dipende_da"]):
                    ordered.append(f)
                    done_nomi.add(f["nome"])
                    remaining.remove(f)

        # Qualcosa rimasto (dipendenza ciclica o errore) — aggiunge in coda
        ordered.extend(remaining)

        # setup prima, loop ultima
        ordered.sort(key=lambda f: priority.get(f["nome"], 1))
        return ordered

    def get_funzione(self, nome: str) -> dict | None:
        for f in self.funzioni:
            if f["nome"] == nome:
                return f
        return None

    def funzioni_scritte(self) -> list[dict]:
        """Funzioni con stato='done' e codice disponibile."""
        return [f for f in self.funzioni if f["stato"] == "done" and f["codice"]]

    # ── Aggiornamento ─────────────────────────────────────────────────────────

    def update_funzione(self, nome: str, stato: str, codice: str = ""):
        for f in self.funzioni:
            if f["nome"] == nome:
                f["stato"] = stato
                if codice:
                    f["codice"] = codice
                self.add_fase(f"func:{nome}", stato)
                return

    def update_stato(self, stato: str):
        self.stato = stato
        self.add_fase("stato", stato)

    def add_errore(self, errore: str, fix: str):
        self.errori_visti.append({"errore": errore[:200], "fix": fix[:200]})

    def add_errore_funzione(self, nome: str, errore: str, fix: str):
        """Associa un errore a una funzione specifica."""
        self.add_errore(f"[{nome}] {errore}", fix)
        # Rimette la funzione in pending per la rigenerazione
        for f in self.funzioni:
            if f["nome"] == nome:
                f["stato"] = "error"

    def add_fase(self, fase: str, risultato: str):
        self.log_fasi.append({
            "fase": fase,
            "risultato": risultato[:300],
            "ts": datetime.utcnow().strftime("%H:%M:%S"),
        })

    # ── Contesto per M40 ─────────────────────────────────────────────────────

    def context_for_globals(self) -> str:
        """Contesto per generare la sezione globals/includes."""
        lines = [
            f"TASK: {self.task}",
            f"BOARD: {self.board}",
        ]
        if self.note_tecniche:
            lines.append("NOTE TECNICHE:")
            for n in self.note_tecniche:
                lines.append(f"  - {n}")
        if self.dipendenze:
            lines.append(f"LIBRERIE DA INCLUDERE: {', '.join(self.dipendenze)}")
        if self.globals_hint:
            lines.append(f"SUGGERIMENTO GLOBALS: {self.globals_hint}")
        # Lista firme future (per dichiarare oggetti globali utili)
        if self.funzioni:
            lines.append("FUNZIONI CHE SEGUIRANNO (firme):")
            for f in self.funzioni:
                lines.append(f"  {f['firma']};")
        return "\n".join(lines)

    def context_for_function(self, nome: str) -> str:
        """
        Contesto compatto per generare UNA funzione.
        Include: globals scritti, firme già disponibili, errori visti.
        """
        func = self.get_funzione(nome)
        if not func:
            return f"TASK: {self.task}\nFUNZIONE: {nome} (non trovata nel piano)"

        lines = [
            f"TASK GLOBALE: {self.task}",
            f"BOARD: {self.board}",
        ]

        if self.globals_code:
            lines.append(f"GLOBALS GIÀ SCRITTI:\n{self.globals_code}")

        # Firme di tutte le funzioni (forward declarations)
        tutte_firme = [f["firma"] for f in self.funzioni if f["nome"] != nome]
        if tutte_firme:
            lines.append("FIRME ALTRE FUNZIONI (già disponibili):")
            for firma in tutte_firme:
                lines.append(f"  {firma};")

        # Corpi delle funzioni già scritte (solo quelle da cui dipende)
        for dep_nome in func["dipende_da"]:
            dep = self.get_funzione(dep_nome)
            if dep and dep["codice"]:
                lines.append(f"FUNZIONE {dep_nome} (già scritta, per riferimento):")
                lines.append(dep["codice"][:400])  # tronca se troppo lunga

        lines.append(f"\nFUNZIONE DA SCRIVERE: {func['firma']}")
        lines.append(f"COMPITO: {func['compito']}")

        if self.note_tecniche:
            lines.append("NOTE TECNICHE:")
            for n in self.note_tecniche:
                lines.append(f"  - {n}")

        if self.errori_visti:
            lines.append("ERRORI GIÀ VISTI (non ripetere):")
            for e in self.errori_visti[-3:]:
                lines.append(f"  • {e['errore']} → {e['fix']}")

        return "\n".join(lines)

    def context_for_generator(self) -> str:
        """Contesto compatto fallback (vecchio flusso senza funzioni)."""
        lines = [
            f"TASK: {self.task}",
            f"BOARD: {self.board}",
        ]
        if self.piano:
            lines.append("PIANO:")
            for i, p in enumerate(self.piano, 1):
                lines.append(f"  {i}. {p}")
        if self.dipendenze:
            lines.append(f"LIBRERIE: {', '.join(self.dipendenze)}")
        if self.note_tecniche:
            lines.append("NOTE TECNICHE:")
            for n in self.note_tecniche:
                lines.append(f"  - {n}")
        if self.errori_visti:
            lines.append("ERRORI GIÀ VISTI (non ripetere):")
            for e in self.errori_visti[-3:]:
                lines.append(f"  • {e['errore']} → {e['fix']}")
        return "\n".join(lines)

    def context_for_evaluator(self, serial_output: str) -> str:
        lines = [
            f"TASK ORIGINALE: {self.task}",
            f"BOARD: {self.board}",
            f"OUTPUT SERIALE:\n{serial_output}",
        ]
        if self.note_tecniche:
            lines.append("NOTE TECNICHE:")
            for n in self.note_tecniche:
                lines.append(f"  - {n}")
        return "\n".join(lines)

    # ── Assemblaggio .ino ─────────────────────────────────────────────────────

    def assemble(self) -> tuple[str, dict]:
        """
        Assembla il .ino finale dalle funzioni generate.
        Ritorna (codice_completo, line_map) dove line_map mappa
        nome_funzione → numero_riga_inizio (per attribuire errori).
        """
        parts = []
        line_map = {}
        current_line = 1

        # 1. Globals
        if self.globals_code:
            parts.append(self.globals_code.rstrip())
            parts.append("")
            current_line += self.globals_code.count("\n") + 2

        # 2. Forward declarations (aiuta il compilatore, non strettamente necessario
        #    per arduino-cli ma rende il codice più robusto)
        fwd = []
        for f in self.funzioni_ordinate():
            nome = f["nome"]
            firma = f["firma"]
            if nome not in ("setup", "loop") and f["codice"]:
                fwd.append(f"{firma};")
        if fwd:
            parts.extend(fwd)
            parts.append("")
            current_line += len(fwd) + 1

        # 3. Funzioni in ordine di dipendenza
        for f in self.funzioni_ordinate():
            if not f["codice"]:
                continue
            line_map[f["nome"]] = current_line
            codice = f["codice"].rstrip()
            parts.append(codice)
            parts.append("")
            current_line += codice.count("\n") + 2

        return "\n".join(parts), line_map

    def funzione_da_errore(self, line_map: dict, error_line: int) -> str | None:
        """
        Dato un numero di riga dell'errore del compilatore,
        ritorna il nome della funzione responsabile.
        """
        candidate = None
        candidate_line = 0
        for nome, start_line in line_map.items():
            if start_line <= error_line and start_line > candidate_line:
                candidate = nome
                candidate_line = start_line
        return candidate

    # ── Stato / riepilogo ─────────────────────────────────────────────────────

    def summary(self) -> str:
        n_done = sum(1 for f in self.funzioni if f["stato"] == "done")
        n_tot = len(self.funzioni)
        return (
            f"[{self.stato.upper()}] {self.task[:50]} | "
            f"funzioni={n_done}/{n_tot} errori={len(self.errori_visti)}"
        )

    def progress(self) -> str:
        """Barra di progresso testuale delle funzioni."""
        if not self.funzioni:
            return "nessuna funzione"
        icons = {"pending": "⬜", "generating": "🔄", "done": "✅", "error": "❌"}
        parts = []
        for f in self.funzioni_ordinate():
            icon = icons.get(f["stato"], "?")
            parts.append(f"{icon} {f['nome']}()")
        return "  ".join(parts)

    # ── Persistenza ───────────────────────────────────────────────────────────

    def save(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "task": self.task,
            "board": self.board,
            "created_at": self.created_at,
            "piano": self.piano,
            "dipendenze": self.dipendenze,
            "note_tecniche": self.note_tecniche,
            "globals_hint": self.globals_hint,
            "globals_code": self.globals_code,
            "funzioni": self.funzioni,
            "stato": self.stato,
            "errori_visti": self.errori_visti,
            "log_fasi": self.log_fasi,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Notebook":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        nb = cls(data["task"], data["board"])
        nb.created_at = data.get("created_at", "")
        nb.piano = data.get("piano", [])
        nb.dipendenze = data.get("dipendenze", [])
        nb.note_tecniche = data.get("note_tecniche", [])
        nb.globals_hint = data.get("globals_hint", "")
        nb.globals_code = data.get("globals_code", "")
        nb.funzioni = data.get("funzioni", [])
        nb.stato = data.get("stato", "planning")
        nb.errori_visti = data.get("errori_visti", [])
        nb.log_fasi = data.get("log_fasi", [])
        return nb
