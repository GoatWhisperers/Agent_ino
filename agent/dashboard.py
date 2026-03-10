"""
Dashboard real-time per l'agente Arduino.

Serve una UI web su http://localhost:7700 con:
  - Header: task corrente
  - Colonna MI50: output streaming con thinking evidenziato
  - Colonna M40: output streaming per funzione
  - Colonna Webcam: thumbnail frame catturati

Avvio automatico quando importato da loop.py.
I client MI50/M40 chiamano dashboard.token() per ogni token.
loop.py chiama dashboard.phase(), dashboard.frame(), ecc.

Nessuna dipendenza esterna oltre Flask (già installato nel venv).
"""

import base64
import json
import os
import queue
import threading
import time
from pathlib import Path

from flask import Flask, Response, request, stream_with_context

# ── Stato globale ──────────────────────────────────────────────────────────────

_app = Flask(__name__)
_clients: list[queue.Queue] = []
_clients_lock = threading.Lock()
_history: list[dict] = []          # eventi recenti (max 500) per nuovi client
_history_lock = threading.Lock()
_server_thread: threading.Thread | None = None
_active = False

PORT = 7700
MAX_HISTORY = 500

# Frame persistenti su disco — sopravvivono al riavvio della dashboard
_FRAMES_CACHE = Path(__file__).parent.parent / "workspace" / ".frames_cache.json"
MAX_CACHED_FRAMES = 20


def _load_frames_cache() -> list[dict]:
    """Carica i frame salvati su disco."""
    try:
        if _FRAMES_CACHE.exists():
            data = json.loads(_FRAMES_CACHE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_frames_cache(frames: list[dict]):
    """Salva i frame su disco (max MAX_CACHED_FRAMES)."""
    try:
        _FRAMES_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FRAMES_CACHE.write_text(
            json.dumps(frames[-MAX_CACHED_FRAMES:], ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


# Frame cache in memoria (solo eventi 'frame', persistiti su disco)
_frames_cache: list[dict] = []
_frames_lock = threading.Lock()


# ── Event bus ─────────────────────────────────────────────────────────────────

def _broadcast(event: dict):
    """Invia evento a tutti i client SSE connessi e lo salva in history."""
    msg = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    with _history_lock:
        _history.append(event)
        if len(_history) > MAX_HISTORY:
            _history.pop(0)
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def emit(event_type: str, **data):
    """Emetti un evento generico al dashboard."""
    if not _active:
        return
    _broadcast({"type": event_type, "ts": time.strftime("%H:%M:%S"), **data})


# ── API pubblica (usata da loop.py e dai client) ───────────────────────────────

def task_start(task: str, board: str):
    emit("task_start", task=task, board=board)

def phase(name: str, detail: str = ""):
    emit("phase", name=name, detail=detail)

def token(source: str, text: str):
    """source: 'mi50' | 'm40'"""
    emit("token", source=source, text=text)

def thinking_start(source: str):
    emit("thinking_start", source=source)

def thinking_end(source: str):
    emit("thinking_end", source=source)

def func_start(nome: str):
    """M40 inizia a generare una funzione."""
    emit("func_start", nome=nome)

def func_done(nome: str, righe: int):
    emit("func_done", nome=nome, righe=righe)

def compile_result(success: bool, errors: list = None, attempt: int = 1):
    emit("compile_result", success=success, errors=errors or [], attempt=attempt)

def serial_output(lines: list[str]):
    emit("serial_output", lines=lines)

def frame(path: str, label: str = ""):
    """Notifica un frame catturato dalla webcam e lo salva su disco."""
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ev = {"type": "frame", "ts": time.strftime("%H:%M:%S"), "b64": b64, "label": label, "path": path}
        # Salva nel buffer persistente
        with _frames_lock:
            _frames_cache.append(ev)
            if len(_frames_cache) > MAX_CACHED_FRAMES:
                _frames_cache.pop(0)
            _save_frames_cache(_frames_cache)
        # Invia ai client connessi
        if _active:
            msg = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            with _history_lock:
                _history.append(ev)
                if len(_history) > MAX_HISTORY:
                    _history.pop(0)
            with _clients_lock:
                dead = []
                for q in _clients:
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        dead.append(q)
                for q in dead:
                    _clients.remove(q)
    except Exception as e:
        emit("frame_error", error=str(e))

def notebook_update(summary: str, progress: str):
    emit("notebook", summary=summary, progress=progress)

def run_end(success: bool, reason: str = ""):
    emit("run_end", success=success, reason=reason)

def log(msg: str, level: str = "info"):
    emit("log", msg=msg, level=level)


# ── Flask routes ──────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arduino Agent Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #e6edf3; font-family: 'Segoe UI', system-ui, sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

  /* Header */
  #header { padding: 12px 20px; background: #161b22; border-bottom: 1px solid #30363d; display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
  #status-dot { width: 10px; height: 10px; border-radius: 50%; background: #444; flex-shrink: 0; transition: background 0.3s; }
  #status-dot.running { background: #3fb950; box-shadow: 0 0 8px #3fb950; animation: pulse 1.5s infinite; }
  #status-dot.done { background: #3fb950; }
  #status-dot.failed { background: #f85149; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  #task-title { font-size: 15px; font-weight: 600; color: #e6edf3; flex: 1; }
  #phase-badge { padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; background: #21262d; color: #8b949e; border: 1px solid #30363d; letter-spacing: 0.5px; }
  #board-badge { padding: 3px 10px; border-radius: 12px; font-size: 11px; background: #1f2f1f; color: #56d364; border: 1px solid #3d6b3d; }
  #time-badge { font-size: 11px; color: #6e7681; font-variant-numeric: tabular-nums; }

  /* 3-column layout */
  #cols { display: flex; flex: 1; overflow: hidden; gap: 1px; background: #30363d; }
  .col { display: flex; flex-direction: column; background: #0d1117; overflow: hidden; }
  #col-mi50 { flex: 1; }
  #col-m40  { flex: 1; }
  #col-cam  { flex: 0 0 260px; }

  .col-header { padding: 8px 14px; background: #161b22; border-bottom: 1px solid #30363d; display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
  .col-label { font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; }
  #col-mi50 .col-label { color: #d2a8ff; }
  #col-m40  .col-label { color: #79c0ff; }
  #col-cam  .col-label { color: #ffa657; }
  .col-sub  { font-size: 10px; color: #6e7681; margin-left: auto; }

  .col-body { flex: 1; overflow-y: auto; padding: 10px 14px; font-size: 12.5px; line-height: 1.65; scroll-behavior: smooth; }
  .col-body::-webkit-scrollbar { width: 4px; }
  .col-body::-webkit-scrollbar-track { background: transparent; }
  .col-body::-webkit-scrollbar-thumb { background: #30363d; border-radius: 2px; }

  /* Text rendering */
  .output-text { white-space: pre-wrap; word-break: break-word; font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace; }
  .thinking { color: #8b949e; font-style: italic; background: #161b22; border-left: 2px solid #444; padding: 2px 8px; margin: 2px 0; border-radius: 0 4px 4px 0; }
  .response { color: #e6edf3; }
  .code-block { color: #a5d6ff; background: #161b22; border-radius: 4px; padding: 8px; margin: 4px 0; border: 1px solid #21262d; }

  /* Func badges */
  .func-header { display: inline-flex; align-items: center; gap: 6px; background: #1c2d3a; border: 1px solid #1f6feb; border-radius: 6px; padding: 3px 10px; margin: 6px 0 3px; font-size: 11px; font-weight: 600; color: #79c0ff; }
  .func-done { background: #1a2e1a; border-color: #3d6b3d; color: #56d364; }

  /* Phase divider */
  .phase-div { margin: 8px 0; padding: 4px 10px; background: #161b22; border-radius: 4px; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase; color: #6e7681; border-left: 3px solid #30363d; }
  .phase-div.mi50 { border-color: #d2a8ff; color: #d2a8ff; }
  .phase-div.m40  { border-color: #79c0ff; color: #79c0ff; }

  /* Compile */
  .compile-ok   { color: #56d364; font-weight: 600; font-size: 11px; }
  .compile-fail { color: #f85149; font-weight: 600; font-size: 11px; }
  .compile-err  { color: #ffa657; font-size: 11px; padding-left: 12px; }

  /* Serial */
  .serial-line { color: #e3b341; font-size: 11px; }

  /* Webcam */
  #frames-grid { display: flex; flex-direction: column; gap: 8px; padding: 8px; overflow-y: auto; flex: 1; }
  .frame-card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; overflow: hidden; cursor: pointer; transition: border-color 0.2s; }
  .frame-card:hover { border-color: #ffa657; }
  .frame-card img { width: 100%; display: block; }
  .frame-label { font-size: 10px; color: #6e7681; padding: 3px 6px; }
  #no-frames { color: #6e7681; font-size: 12px; text-align: center; padding: 40px 20px; }

  /* Lightbox */
  #lightbox { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 100; align-items: center; justify-content: center; }
  #lightbox.open { display: flex; }
  #lightbox img { max-width: 90vw; max-height: 90vh; border-radius: 8px; }

  /* Connection lost */
  #conn-banner { display: none; position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); background: #f85149; color: white; padding: 8px 20px; border-radius: 6px; font-size: 12px; font-weight: 600; z-index: 200; }
  #conn-banner.show { display: block; }

  /* Scrollbar for cam col */
  #col-cam { display: flex; flex-direction: column; }
  #col-cam .col-body { padding: 0; display: flex; flex-direction: column; overflow: hidden; }
</style>
</head>
<body>

<div id="header">
  <div id="status-dot"></div>
  <div id="task-title">In attesa del task...</div>
  <div id="board-badge" style="display:none"></div>
  <div id="phase-badge">IDLE</div>
  <div id="time-badge">--:--:--</div>
</div>

<div id="cols">
  <div class="col" id="col-mi50">
    <div class="col-header">
      <span class="col-label">MI50 — Qwen3.5-9B</span>
      <span class="col-sub" id="mi50-tokens">0 tok</span>
    </div>
    <div class="col-body output-text" id="mi50-body"></div>
  </div>

  <div class="col" id="col-m40">
    <div class="col-header">
      <span class="col-label">M40 — Qwen3.5-9B Q5_K_M</span>
      <span class="col-sub" id="m40-tokens">0 tok</span>
    </div>
    <div class="col-body output-text" id="m40-body"></div>
  </div>

  <div class="col" id="col-cam">
    <div class="col-header">
      <span class="col-label">Webcam</span>
      <span class="col-sub" id="cam-count">0 frame</span>
    </div>
    <div class="col-body">
      <div id="frames-grid">
        <div id="no-frames">Nessun frame ancora.<br>La webcam si attiva quando<br>il piano prevede vcap.</div>
      </div>
    </div>
  </div>
</div>

<div id="lightbox">
  <img id="lightbox-img" src="" alt="frame">
</div>
<div id="conn-banner">Connessione persa — riconnessione...</div>

<script>
const mi50Body = document.getElementById('mi50-body');
const m40Body  = document.getElementById('m40-body');
const mi50Tok  = document.getElementById('mi50-tokens');
const m40Tok   = document.getElementById('m40-tokens');
const taskTitle = document.getElementById('task-title');
const phaseBadge = document.getElementById('phase-badge');
const boardBadge = document.getElementById('board-badge');
const statusDot  = document.getElementById('status-dot');
const timeBadge  = document.getElementById('time-badge');
const framesGrid = document.getElementById('frames-grid');
const noFrames   = document.getElementById('no-frames');
const camCount   = document.getElementById('cam-count');
const lightbox   = document.getElementById('lightbox');
const lightboxImg= document.getElementById('lightbox-img');
const connBanner = document.getElementById('conn-banner');

let mi50TokenCount = 0;
let m40TokenCount  = 0;
let frameCount     = 0;
let mi50Thinking   = false;
let startTime      = null;

// Current text nodes
let mi50Current = null;
let m40Current  = null;
let m40FuncDiv  = null;

function newTextNode(parent, cls) {
  const span = document.createElement('span');
  span.className = cls;
  parent.appendChild(span);
  return span;
}

function autoScroll(el) {
  el.scrollTop = el.scrollHeight;
}

function setStatus(s) {
  statusDot.className = '';
  if (s) statusDot.classList.add(s);
}

// Timer
function startTimer() {
  startTime = Date.now();
  const t = setInterval(() => {
    if (!startTime) { clearInterval(t); return; }
    const s = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(s / 60);
    timeBadge.textContent = `${String(m).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
  }, 1000);
}

// Event handlers
function handleEvent(ev) {
  switch(ev.type) {

    case 'task_start':
      taskTitle.textContent = ev.task;
      boardBadge.textContent = ev.board;
      boardBadge.style.display = '';
      mi50Body.innerHTML = '';
      m40Body.innerHTML = '';
      framesGrid.innerHTML = '<div id="no-frames">Nessun frame ancora.</div>';
      noFrames.style.display = '';
      mi50TokenCount = m40TokenCount = frameCount = 0;
      mi50Tok.textContent = '0 tok';
      m40Tok.textContent  = '0 tok';
      camCount.textContent = '0 frame';
      mi50Current = m40Current = m40FuncDiv = null;
      mi50Thinking = false;
      setStatus('running');
      startTimer();
      break;

    case 'phase':
      phaseBadge.textContent = ev.name.toUpperCase();
      // Divider in MI50 col
      const div = document.createElement('div');
      div.className = 'phase-div mi50';
      div.textContent = '── ' + ev.name + (ev.detail ? ': ' + ev.detail : '') + ' ──';
      mi50Body.appendChild(div);
      mi50Current = null;
      autoScroll(mi50Body);
      break;

    case 'thinking_start':
      if (ev.source === 'mi50') {
        mi50Current = newTextNode(mi50Body, 'thinking');
        mi50Current.textContent = '💭 ';
        mi50Thinking = true;
      }
      break;

    case 'thinking_end':
      if (ev.source === 'mi50') {
        mi50Thinking = false;
        mi50Current = null;
      }
      break;

    case 'token':
      if (ev.source === 'mi50') {
        let txt = ev.text;
        // detect think tags inline
        if (txt.includes('<think>')) {
          mi50Thinking = true;
          mi50Current = newTextNode(mi50Body, 'thinking');
          mi50Current.textContent = '💭 ';
          txt = txt.replace('<think>', '');
        }
        if (txt.includes('</think>')) {
          mi50Thinking = false;
          txt = txt.replace('</think>', '');
          mi50Current = null;
        }
        if (txt) {
          if (!mi50Current) {
            mi50Current = newTextNode(mi50Body, mi50Thinking ? 'thinking' : 'response');
          }
          mi50Current.textContent += txt;
        }
        mi50TokenCount++;
        if (mi50TokenCount % 10 === 0) {
          mi50Tok.textContent = mi50TokenCount + ' tok';
          autoScroll(mi50Body);
        }
      } else if (ev.source === 'm40') {
        if (!m40Current) {
          const cls = ev.text.includes('```') || ev.text.includes('{') ? 'code-block' : 'response';
          m40Current = newTextNode(m40FuncDiv || m40Body, cls);
        }
        m40Current.textContent += ev.text;
        m40TokenCount++;
        if (m40TokenCount % 10 === 0) {
          m40Tok.textContent = m40TokenCount + ' tok';
          autoScroll(m40Body);
        }
      }
      break;

    case 'func_start':
      m40Current = null;
      m40FuncDiv = document.createElement('div');
      const badge = document.createElement('div');
      badge.className = 'func-header';
      badge.innerHTML = '⚙ <code>' + ev.nome + '()</code>';
      badge.id = 'func-' + ev.nome;
      m40FuncDiv.appendChild(badge);
      m40Body.appendChild(m40FuncDiv);
      autoScroll(m40Body);
      break;

    case 'func_done': {
      m40Current = null;
      const b = document.getElementById('func-' + ev.nome);
      if (b) {
        b.className = 'func-header func-done';
        b.innerHTML = '✓ <code>' + ev.nome + '()</code> <span style="color:#6e7681;font-size:10px">' + ev.righe + ' righe</span>';
      }
      autoScroll(m40Body);
      break;
    }

    case 'compile_result': {
      const div2 = document.createElement('div');
      if (ev.success) {
        div2.className = 'compile-ok';
        div2.textContent = '✅ Compilazione OK (tentativo ' + ev.attempt + ')';
      } else {
        div2.className = 'compile-fail';
        div2.textContent = '❌ Errori compilazione (tentativo ' + ev.attempt + ')';
        (ev.errors || []).slice(0,3).forEach(e => {
          const ed = document.createElement('div');
          ed.className = 'compile-err';
          ed.textContent = '  riga ' + e.line + ': ' + e.message;
          div2.appendChild(ed);
        });
      }
      mi50Body.appendChild(div2);
      autoScroll(mi50Body);
      break;
    }

    case 'serial_output': {
      const sd = document.createElement('div');
      sd.style.marginTop = '6px';
      (ev.lines || []).forEach(l => {
        const ld = document.createElement('div');
        ld.className = 'serial-line';
        ld.textContent = '▶ ' + l;
        sd.appendChild(ld);
      });
      mi50Body.appendChild(sd);
      autoScroll(mi50Body);
      break;
    }

    case 'frame': {
      frameCount++;
      camCount.textContent = frameCount + ' frame';
      const nf = document.getElementById('no-frames');
      if (nf) nf.remove();
      const card = document.createElement('div');
      card.className = 'frame-card';
      const img = document.createElement('img');
      img.src = 'data:image/jpeg;base64,' + ev.b64;
      img.alt = ev.label || 'frame';
      img.onclick = () => { lightboxImg.src = img.src; lightbox.classList.add('open'); };
      const lbl = document.createElement('div');
      lbl.className = 'frame-label';
      lbl.textContent = (ev.label || 'frame') + ' — ' + ev.ts;
      card.appendChild(img);
      card.appendChild(lbl);
      // Inserisci in cima
      framesGrid.insertBefore(card, framesGrid.firstChild);
      break;
    }

    case 'notebook': {
      const nd = document.createElement('div');
      nd.style.cssText = 'font-size:10px;color:#6e7681;margin:4px 0;padding:4px 8px;background:#161b22;border-radius:4px;';
      nd.textContent = ev.progress;
      m40Body.appendChild(nd);
      autoScroll(m40Body);
      break;
    }

    case 'run_end':
      setStatus(ev.success ? 'done' : 'failed');
      phaseBadge.textContent = ev.success ? 'DONE ✓' : 'FAILED ✗';
      startTime = null;
      break;

    case 'log': {
      const ld = document.createElement('div');
      ld.style.cssText = 'font-size:10px;color:#6e7681;margin:1px 0;';
      ld.textContent = ev.msg;
      mi50Body.appendChild(ld);
      break;
    }
  }
}

// Lightbox close
lightbox.onclick = () => lightbox.classList.remove('open');

// SSE connection
let evtSource = null;
function connect() {
  evtSource = new EventSource('/events');
  evtSource.onopen = () => connBanner.classList.remove('show');
  evtSource.onmessage = (e) => {
    try { handleEvent(JSON.parse(e.data)); } catch(ex) { console.error(ex); }
  };
  evtSource.onerror = () => {
    connBanner.classList.add('show');
    evtSource.close();
    setTimeout(connect, 3000);
  };
}
connect();
</script>
</body>
</html>"""


@_app.get("/")
def index():
    return _HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@_app.get("/events")
def events():
    q: queue.Queue = queue.Queue(maxsize=200)
    # Manda history al nuovo client
    with _history_lock:
        hist_copy = list(_history)
    with _clients_lock:
        _clients.append(q)

    def stream():
        # Prima manda la history
        for ev in hist_copy:
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        # Poi ascolta eventi live
        while True:
            try:
                msg = q.get(timeout=25)
                yield msg
            except queue.Empty:
                yield ": keepalive\n\n"

    return Response(
        stream_with_context(stream()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Avvio server ──────────────────────────────────────────────────────────────

def start(port: int = PORT):
    """Avvia il dashboard server in un thread daemon."""
    global _server_thread, _active, _frames_cache

    if _server_thread and _server_thread.is_alive():
        return  # già avviato

    _active = True

    # Carica i frame persistenti dal disco nella history e nel buffer in-memory
    saved_frames = _load_frames_cache()
    if saved_frames:
        with _frames_lock:
            _frames_cache = saved_frames[-MAX_CACHED_FRAMES:]
        with _history_lock:
            _history.extend(_frames_cache)
            if len(_history) > MAX_HISTORY:
                del _history[:len(_history) - MAX_HISTORY]

    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)  # silenzia i log Flask in console

    def _run():
        _app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)

    _server_thread = threading.Thread(target=_run, daemon=True)
    _server_thread.start()
    time.sleep(0.5)
    print(f"\n  📊 Dashboard: http://localhost:{port}\n", flush=True)


def stop():
    global _active
    _active = False
