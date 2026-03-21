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
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, stream_with_context

# ── Stato globale ──────────────────────────────────────────────────────────────

_app = Flask(__name__)
_clients: list[queue.Queue] = []
_agent_proc: subprocess.Popen | None = None
_agent_lock = threading.Lock()
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
  #main-area { flex: 1; overflow: hidden; display: flex; }

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
  #cols { display: flex; flex: 1; overflow: hidden; gap: 1px; background: #30363d; width: 100%; }
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
  #conn-banner { display: none; position: fixed; bottom: 56px; left: 50%; transform: translateX(-50%); background: #f85149; color: white; padding: 8px 20px; border-radius: 6px; font-size: 12px; font-weight: 600; z-index: 200; }
  #conn-banner.show { display: block; }

  /* Scrollbar for cam col */
  #col-cam { display: flex; flex-direction: column; }
  #col-cam .col-body { padding: 0; display: flex; flex-direction: column; overflow: hidden; }

  /* Task bar */
  #taskbar { padding: 8px 16px; background: #161b22; border-top: 1px solid #30363d; display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
  #taskbar textarea { flex: 1; background: #0d1117; color: #e6edf3; border: 1px solid #30363d; border-radius: 6px; padding: 6px 10px; font-size: 12px; font-family: inherit; resize: none; height: 38px; line-height: 1.4; outline: none; transition: border-color 0.2s; }
  #taskbar textarea:focus { border-color: #58a6ff; }
  #fqbn-select { background: #0d1117; color: #e6edf3; border: 1px solid #30363d; border-radius: 6px; padding: 5px 8px; font-size: 11px; outline: none; cursor: pointer; }
  #btn-start { background: #238636; color: white; border: none; border-radius: 6px; padding: 7px 18px; font-size: 12px; font-weight: 600; cursor: pointer; transition: background 0.2s; white-space: nowrap; }
  #btn-start:hover { background: #2ea043; }
  #btn-start:disabled { background: #444; cursor: not-allowed; }
  #btn-stop { background: #b91c1c; color: white; border: none; border-radius: 6px; padding: 7px 14px; font-size: 12px; font-weight: 600; cursor: pointer; transition: background 0.2s; white-space: nowrap; }
  #btn-stop:hover { background: #dc2626; }
  #btn-stop:disabled { background: #444; cursor: not-allowed; }
  #agent-status { font-size: 10px; color: #6e7681; white-space: nowrap; }
  #agent-status.running { color: #3fb950; }

  /* Webcam test frame */
  #test-frame-box { padding: 8px; border-bottom: 1px solid #30363d; flex-shrink: 0; display: none; }
  #test-frame-box img { width: 100%; border-radius: 4px; display: block; cursor: pointer; }
  #test-frame-label { font-size: 10px; color: #ffa657; margin-top: 3px; text-align: center; }
  #btn-grab { background: #1f2d3a; color: #ffa657; border: 1px solid #ffa657; border-radius: 5px; padding: 3px 10px; font-size: 10px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
  #btn-grab:hover { background: #2d4156; }
  #btn-grab:disabled { opacity: 0.5; cursor: not-allowed; }
  #btn-clear-frames { background: #1f2020; color: #6e7681; border: 1px solid #444; border-radius: 5px; padding: 3px 8px; font-size: 10px; cursor: pointer; transition: background 0.2s; }
  #btn-clear-frames:hover { color: #f85149; border-color: #f85149; }
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

<div id="main-area"><div id="cols">
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
      <button id="btn-grab" onclick="grabTestFrame()">📷 Scatta</button>
      <button id="btn-clear-frames" onclick="clearFrames()">🗑</button>
      <span class="col-sub" id="cam-count">0 frame</span>
    </div>
    <div id="test-frame-box">
      <img id="test-frame-img" src="" alt="test frame" onclick="lightboxImg.src=this.src;lightbox.classList.add('open')">
      <div id="test-frame-label">test</div>
    </div>
    <div class="col-body">
      <div id="frames-grid">
        <div id="no-frames">Nessun frame ancora.<br>La webcam si attiva quando<br>il piano prevede vcap.</div>
      </div>
    </div>
  </div>
</div></div>

<div id="taskbar">
  <textarea id="task-input" placeholder="Descrivi il task Arduino... (es: mostra un cerchio sul display OLED)" rows="1"></textarea>
  <select id="fqbn-select">
    <option value="esp32:esp32:esp32">ESP32</option>
    <option value="arduino:avr:uno">Arduino Uno</option>
    <option value="arduino:avr:mega">Arduino Mega</option>
  </select>
  <button id="btn-start" onclick="startTask()">▶ Start</button>
  <button id="btn-stop" onclick="stopTask()" disabled>■ Stop</button>
  <span id="agent-status">inattivo</span>
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
      } else if (ev.source === 'm40' || ev.source === 'm40-think') {
        const isThink = ev.source === 'm40-think';
        if (!m40Current || (isThink !== (m40Current.className === 'thinking'))) {
          const cls = isThink ? 'thinking' : (ev.text.includes('```') || ev.text.includes('{') ? 'code-block' : 'response');
          m40Current = newTextNode(m40FuncDiv || m40Body, cls);
          if (isThink && m40Current.textContent === '') m40Current.textContent = '💭 ';
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

// ── Webcam test frame ──────────────────────────────────────────────────────────
const btnGrab = document.getElementById('btn-grab');
const testFrameBox = document.getElementById('test-frame-box');
const testFrameImg = document.getElementById('test-frame-img');
const testFrameLabel = document.getElementById('test-frame-label');

async function clearFrames() {
  await fetch('/clear_frames', {method:'POST'});
  testFrameBox.style.display = 'none';
  testFrameImg.src = '';
  framesGrid.innerHTML = '<div id="no-frames">Nessun frame ancora.<br>La webcam si attiva quando<br>il piano prevede vcap.</div>';
  frameCount = 0;
  camCount.textContent = '0 frame';
}

async function grabTestFrame() {
  btnGrab.disabled = true;
  btnGrab.textContent = '⏳';
  try {
    const r = await fetch('/grab_test', {method:'POST'});
    const data = await r.json();
    if (data.error) {
      testFrameLabel.textContent = '❌ ' + data.error;
      testFrameBox.style.display = 'block';
    } else {
      testFrameImg.src = 'data:image/jpeg;base64,' + data.b64;
      testFrameLabel.textContent = '📷 ' + new Date().toLocaleTimeString();
      testFrameBox.style.display = 'block';
    }
  } catch(e) {
    testFrameLabel.textContent = '❌ Errore: ' + e.message;
    testFrameBox.style.display = 'block';
  } finally {
    btnGrab.disabled = false;
    btnGrab.textContent = '📷 Scatta';
  }
}

// ── Task control ───────────────────────────────────────────────────────────────
const taskInput = document.getElementById('task-input');
const fqbnSelect = document.getElementById('fqbn-select');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const agentStatus = document.getElementById('agent-status');

function setAgentRunning(running, pid) {
  if (running) {
    btnStart.disabled = true;
    btnStop.disabled = false;
    agentStatus.className = 'running';
    agentStatus.textContent = pid ? 'running (pid ' + pid + ')' : 'running...';
  } else {
    btnStart.disabled = false;
    btnStop.disabled = true;
    agentStatus.className = '';
    agentStatus.textContent = 'inattivo';
  }
}

function clearAll() {
  mi50Body.innerHTML = '';
  m40Body.innerHTML = '';
  framesGrid.innerHTML = '<div id="no-frames">Nessun frame ancora.</div>';
  testFrameBox.style.display = 'none';
  testFrameImg.src = '';
  frameCount = 0; mi50TokenCount = 0; m40TokenCount = 0;
  mi50Tok.textContent = '0 tok'; m40Tok.textContent = '0 tok';
  camCount.textContent = '0 frame';
  mi50Current = m40Current = m40FuncDiv = null;
  fetch('/clear_frames', {method:'POST'});
}

async function startTask() {
  const task = taskInput.value.trim();
  if (!task) { taskInput.focus(); return; }
  clearAll();
  setAgentRunning(true);
  try {
    const r = await fetch('/run_task', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({task, fqbn: fqbnSelect.value})
    });
    const data = await r.json();
    if (data.error) {
      setAgentRunning(false);
      agentStatus.textContent = '❌ ' + data.error;
    } else {
      setAgentRunning(true, data.pid);
      pollAgentStatus();
    }
  } catch(e) {
    setAgentRunning(false);
    agentStatus.textContent = '❌ ' + e.message;
  }
}

async function stopTask() {
  try { await fetch('/stop_task', {method:'POST'}); } catch(e) {}
  setAgentRunning(false);
}

function pollAgentStatus() {
  const interval = setInterval(async () => {
    try {
      const r = await fetch('/agent_status');
      const data = await r.json();
      if (!data.running) {
        clearInterval(interval);
        setAgentRunning(false);
      }
    } catch(e) { clearInterval(interval); }
  }, 2000);
}

// Controlla stato agente al caricamento pagina
(async () => {
  try {
    const r = await fetch('/agent_status');
    const data = await r.json();
    setAgentRunning(data.running, data.pid);
    if (data.running) pollAgentStatus();
  } catch(e) {}
})();

// Auto-expand textarea
taskInput.addEventListener('input', function() {
  this.style.height = '38px';
  this.style.height = Math.min(this.scrollHeight, 100) + 'px';
});
// Start on Ctrl+Enter
taskInput.addEventListener('keydown', function(e) {
  if (e.ctrlKey && e.key === 'Enter') startTask();
});

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


@_app.post("/grab_test")
def grab_test():
    """Cattura un frame dalla webcam del Raspberry per test posizionamento."""
    try:
        from agent.grab import grab_now
        result = grab_now(n_frames=1)
        if not result.get("ok") or not result.get("frame_paths"):
            err = result.get("error") or "Nessun frame catturato"
            return jsonify({"error": err}), 500
        path = result["frame_paths"][0]
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return jsonify({"b64": b64, "path": path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@_app.post("/emit")
def emit_route():
    """Endpoint per subprocess che non hanno la dashboard attiva localmente."""
    data = request.get_json() or {}
    event_type = data.pop("type", "log")
    ts = data.pop("ts", time.strftime("%H:%M:%S"))

    # Gestione speciale per frame: path → base64
    if event_type == "frame":
        path = data.get("path", "")
        if path and not data.get("b64"):
            try:
                with open(path, "rb") as f:
                    data["b64"] = base64.b64encode(f.read()).decode()
                ev = {"type": "frame", "ts": ts, **data}
                with _frames_lock:
                    _frames_cache.append(ev)
                    if len(_frames_cache) > MAX_CACHED_FRAMES:
                        _frames_cache.pop(0)
                    _save_frames_cache(_frames_cache)
                msg = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                with _history_lock:
                    _history.append(ev)
                with _clients_lock:
                    for q in list(_clients):
                        try:
                            q.put_nowait(msg)
                        except queue.Full:
                            pass
                return jsonify({"ok": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    _broadcast({"type": event_type, "ts": ts, **data})
    return jsonify({"ok": True})


@_app.post("/clear_frames")
def clear_frames_route():
    """Svuota cache frame su disco e rimuove i frame dalla history."""
    with _frames_lock:
        _frames_cache.clear()
        _save_frames_cache([])
    with _history_lock:
        _history[:] = [e for e in _history if e.get("type") != "frame"]
    return jsonify({"ok": True})


@_app.post("/run_task")
def run_task():
    """Avvia agent/loop.py con il task dato."""
    global _agent_proc
    data = request.get_json() or {}
    task = (data.get("task") or "").strip()
    fqbn = data.get("fqbn") or "esp32:esp32:esp32"
    if not task:
        return jsonify({"error": "task vuoto"}), 400
    with _agent_lock:
        if _agent_proc and _agent_proc.poll() is None:
            return jsonify({"error": "Agente già in esecuzione (pid {})".format(_agent_proc.pid)}), 409
        project_root = Path(__file__).parent.parent
        # Usa il Python del venv corretto, non sys.executable (che potrebbe essere un altro progetto)
        venv_python = project_root / ".venv" / "bin" / "python3"
        python = str(venv_python) if venv_python.exists() else sys.executable
        cmd = [python, "agent/tool_agent.py", task, "--fqbn", fqbn]
        log_file = open("/tmp/tool_agent.log", "w")
        _agent_proc = subprocess.Popen(
            cmd, cwd=str(project_root),
            stdout=log_file, stderr=log_file
        )
    return jsonify({"ok": True, "pid": _agent_proc.pid})


@_app.post("/stop_task")
def stop_task():
    """Ferma il processo loop.py in esecuzione."""
    global _agent_proc
    with _agent_lock:
        if _agent_proc and _agent_proc.poll() is None:
            _agent_proc.terminate()
            return jsonify({"ok": True, "note": "SIGTERM inviato"})
    return jsonify({"ok": True, "note": "nessun processo attivo"})


@_app.get("/agent_status")
def agent_status_route():
    """Stato corrente dell'agente."""
    with _agent_lock:
        if _agent_proc is None:
            return jsonify({"running": False})
        running = _agent_proc.poll() is None
        return jsonify({"running": running, "pid": _agent_proc.pid})


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

    _server_thread = threading.Thread(target=_run, daemon=False)
    _server_thread.start()
    time.sleep(0.5)
    print(f"\n  📊 Dashboard: http://localhost:{port}\n", flush=True)


def stop():
    global _active
    _active = False
