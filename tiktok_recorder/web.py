"""
Web-Oberfläche für den TikTok Live Recorder.

Startet einen lokalen Flask-Server und liefert eine Single-Page-App aus.
Alle Aktionen (Streamer hinzufügen, splitten, abspielen, …) laufen über
JSON-REST-Endpoints.

Aufruf:  siehe main.py -> run_web()
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import webbrowser
from functools import wraps
from pathlib import Path
from typing import Optional

from flask import Flask, Response, abort, jsonify, request, send_file

from . import database as db
from .config import load_config, save_config
from .recorder import RecorderManager

log = logging.getLogger("web")

# Globale Referenz auf den Manager — wird in run_web() gesetzt
_manager: Optional[RecorderManager] = None


# --------------------------------------------------------------------------- #
# HTML-Single-Page-App (inline, damit alles in einer Datei bleibt)
# --------------------------------------------------------------------------- #

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="de" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0a0a0a">
<title>TikTok Live Recorder</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root[data-theme="dark"] {
    --bg: #0a0a0a;
    --bg-elev: #111111;
    --surface: #161616;
    --surface-hover: #1d1d1d;
    --border: #232323;
    --border-strong: #2e2e2e;
    --text: #f5f5f5;
    --text-dim: #a1a1a1;
    --text-faint: #6b6b6b;
    --accent: #f5f5f5;
    --accent-fg: #0a0a0a;
    --live: #ef4444;
    --live-bg: rgba(239, 68, 68, 0.1);
    --live-border: rgba(239, 68, 68, 0.3);
    --success: #22c55e;
    --warning: #eab308;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
    --shadow-lg: 0 16px 40px rgba(0,0,0,0.6);
  }
  :root[data-theme="light"] {
    --bg: #ffffff;
    --bg-elev: #fafafa;
    --surface: #ffffff;
    --surface-hover: #f5f5f5;
    --border: #e5e5e5;
    --border-strong: #d4d4d4;
    --text: #0a0a0a;
    --text-dim: #525252;
    --text-faint: #a3a3a3;
    --accent: #0a0a0a;
    --accent-fg: #ffffff;
    --live: #dc2626;
    --live-bg: rgba(220, 38, 38, 0.08);
    --live-border: rgba(220, 38, 38, 0.25);
    --success: #16a34a;
    --warning: #ca8a04;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
    --shadow-md: 0 2px 8px rgba(0,0,0,0.06);
    --shadow-lg: 0 16px 40px rgba(0,0,0,0.12);
  }

  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; margin: 0; padding: 0; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    font-size: 14px; line-height: 1.5;
    -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
    min-height: 100vh;
    transition: background 0.2s ease, color 0.2s ease;
  }

  header {
    border-bottom: 1px solid var(--border);
    background: var(--bg);
    position: sticky; top: 0; z-index: 50;
  }
  .header-inner {
    max-width: 1280px; margin: 0 auto; padding: 16px 24px;
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
  }
  .brand {
    display: flex; align-items: center; gap: 10px;
    font-weight: 600; font-size: 15px; letter-spacing: -0.01em;
  }
  .brand-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--live); box-shadow: 0 0 10px var(--live);
  }
  .header-actions { display: flex; align-items: center; gap: 8px; }
  .status-pill {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 6px 12px; border-radius: 999px;
    background: var(--surface); border: 1px solid var(--border);
    font-size: 12px; color: var(--text-dim);
    font-family: 'JetBrains Mono', monospace;
  }
  .status-pill.active {
    background: var(--live-bg); border-color: var(--live-border); color: var(--live);
  }
  .status-pill .dot {
    width: 6px; height: 6px; border-radius: 50%; background: var(--text-faint);
  }
  .status-pill.active .dot {
    background: var(--live); animation: pulse 1.6s ease-in-out infinite;
  }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

  .icon-btn {
    width: 36px; height: 36px; border-radius: 8px;
    background: transparent; border: 1px solid var(--border);
    color: var(--text-dim); cursor: pointer;
    display: inline-flex; align-items: center; justify-content: center;
    transition: all 0.15s ease;
  }
  .icon-btn:hover { background: var(--surface-hover); color: var(--text); border-color: var(--border-strong); }
  .icon-btn svg { width: 16px; height: 16px; }

  .tabbar {
    border-bottom: 1px solid var(--border);
    background: var(--bg);
    position: sticky; top: 69px; z-index: 40;
  }
  .tabbar-inner {
    max-width: 1280px; margin: 0 auto; padding: 0 24px;
    display: flex; gap: 0; overflow-x: auto;
    scrollbar-width: none;
  }
  .tabbar-inner::-webkit-scrollbar { display: none; }
  .tab-btn {
    background: none; border: none; color: var(--text-dim);
    padding: 14px 0; margin-right: 28px;
    font-family: inherit; font-size: 14px; font-weight: 500;
    cursor: pointer; border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    transition: color 0.15s ease, border-color 0.15s ease;
    white-space: nowrap;
  }
  .tab-btn:hover { color: var(--text); }
  .tab-btn.active { color: var(--text); border-bottom-color: var(--accent); }
  .tab-count {
    display: inline-block; margin-left: 6px;
    padding: 1px 6px; border-radius: 4px;
    background: var(--surface); color: var(--text-dim);
    font-size: 11px; font-weight: 500;
    font-family: 'JetBrains Mono', monospace;
  }
  .tab-btn.active .tab-count { background: var(--bg-elev); color: var(--text); }

  main { max-width: 1280px; margin: 0 auto; padding: 32px 24px 120px; }
  .tab { display: none; }
  .tab.active { display: block; }

  .page-head {
    display: flex; align-items: flex-end; justify-content: space-between;
    margin-bottom: 28px; gap: 20px; flex-wrap: wrap;
  }
  .page-title { font-size: 22px; font-weight: 600; letter-spacing: -0.01em; }
  .page-sub { color: var(--text-dim); font-size: 13px; margin-top: 4px; }

  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    background: var(--surface); color: var(--text);
    border: 1px solid var(--border);
    padding: 8px 14px; border-radius: 8px;
    font-family: inherit; font-size: 13px; font-weight: 500;
    cursor: pointer; transition: all 0.15s ease;
    min-height: 36px; white-space: nowrap;
    touch-action: manipulation;
  }
  .btn:hover { background: var(--surface-hover); border-color: var(--border-strong); }
  .btn:active { transform: translateY(0.5px); }
  .btn.primary {
    background: var(--accent); color: var(--accent-fg); border-color: var(--accent);
  }
  .btn.primary:hover { opacity: 0.9; }
  .btn.danger { color: var(--live); }
  .btn.danger:hover { background: var(--live-bg); border-color: var(--live-border); }
  .btn.split { color: var(--warning); border-color: var(--border); }
  .btn.split:hover { background: var(--surface-hover); }
  .btn.lg { padding: 11px 18px; font-size: 14px; min-height: 42px; }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn svg { width: 14px; height: 14px; }

  .add-bar { display: flex; gap: 8px; margin-bottom: 24px; }
  .add-bar input {
    flex: 1; min-width: 0;
    background: var(--surface); border: 1px solid var(--border);
    color: var(--text); padding: 11px 14px; border-radius: 8px;
    font-family: inherit; font-size: 14px;
    transition: border-color 0.15s ease;
  }
  .add-bar input::placeholder { color: var(--text-faint); }
  .add-bar input:focus { outline: none; border-color: var(--text-dim); }

  .streamer-list {
    border: 1px solid var(--border); border-radius: 10px;
    background: var(--surface); overflow: hidden;
  }
  .streamer-row {
    display: flex; align-items: center; gap: 14px;
    padding: 14px 18px; border-bottom: 1px solid var(--border);
    transition: background 0.15s ease;
  }
  .streamer-row:last-child { border-bottom: none; }
  .streamer-row:hover { background: var(--surface-hover); }
  .streamer-avatar {
    width: 36px; height: 36px; border-radius: 50%;
    background: var(--bg-elev); border: 1px solid var(--border);
    display: flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 600; color: var(--text-dim);
    flex-shrink: 0;
  }
  .streamer-row.live .streamer-avatar {
    background: var(--live-bg); border-color: var(--live-border); color: var(--live);
  }
  .streamer-info { flex: 1; min-width: 0; }
  .streamer-name {
    font-weight: 600; font-size: 14px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .streamer-meta {
    color: var(--text-faint); font-size: 12px; margin-top: 2px;
    font-family: 'JetBrains Mono', monospace;
  }
  .streamer-status {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 999px;
    font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
    background: var(--bg-elev); color: var(--text-faint);
    border: 1px solid var(--border);
    flex-shrink: 0;
  }
  .live .streamer-status {
    background: var(--live-bg); border-color: var(--live-border); color: var(--live);
  }
  .streamer-status .dot {
    width: 6px; height: 6px; border-radius: 50%; background: currentColor;
  }
  .live .streamer-status .dot { animation: pulse 1.6s ease-in-out infinite; }
  .streamer-actions { display: flex; gap: 6px; flex-shrink: 0; }

  .toolbar {
    display: flex; align-items: center; gap: 10px;
    margin-bottom: 16px; flex-wrap: wrap;
  }
  .select {
    background: var(--surface); border: 1px solid var(--border);
    color: var(--text); padding: 8px 14px; border-radius: 8px;
    font-family: inherit; font-size: 13px; min-height: 36px;
    cursor: pointer;
  }
  .select:focus { outline: none; border-color: var(--text-dim); }
  .toolbar-spacer { flex: 1; }

  .rec-list {
    border: 1px solid var(--border); border-radius: 10px;
    background: var(--surface); overflow: hidden;
  }
  .rec-list-head {
    display: grid;
    grid-template-columns: 44px 1fr 140px 90px 90px 100px;
    align-items: center; gap: 12px;
    padding: 12px 18px;
    background: var(--bg-elev);
    border-bottom: 1px solid var(--border);
    font-size: 11px; font-weight: 600; color: var(--text-faint);
    text-transform: uppercase; letter-spacing: 0.06em;
  }
  .rec-row {
    display: grid;
    grid-template-columns: 44px 1fr 140px 90px 90px 100px;
    align-items: center; gap: 12px;
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.15s ease;
  }
  .rec-row:last-child { border-bottom: none; }
  .rec-row:hover { background: var(--surface-hover); }
  .rec-row.selected { background: var(--surface-hover); }

  .rec-info { min-width: 0; }
  .rec-streamer { font-weight: 600; font-size: 14px; }
  .rec-file {
    color: var(--text-faint); font-size: 11px; margin-top: 2px;
    font-family: 'JetBrains Mono', monospace;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .rec-cell {
    color: var(--text-dim); font-size: 13px;
    font-family: 'JetBrains Mono', monospace;
  }
  .rec-actions-cell { display: flex; gap: 4px; justify-content: flex-end; }
  .rec-actions-cell .icon-btn { width: 30px; height: 30px; border-radius: 6px; }
  .rec-actions-cell .icon-btn svg { width: 13px; height: 13px; }

  .check { position: relative; width: 18px; height: 18px; flex-shrink: 0; }
  .check input {
    position: absolute; opacity: 0; cursor: pointer;
    width: 100%; height: 100%; margin: 0;
  }
  .check-mark {
    display: block; width: 18px; height: 18px;
    background: var(--bg);
    border: 1.5px solid var(--border-strong);
    border-radius: 5px;
    transition: all 0.15s ease;
  }
  .check input:checked + .check-mark {
    background: var(--accent); border-color: var(--accent);
  }
  .check input:checked + .check-mark::after {
    content: ''; position: absolute; left: 5px; top: 1px;
    width: 5px; height: 10px;
    border: solid var(--accent-fg);
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
  }
  .check input:indeterminate + .check-mark {
    background: var(--accent); border-color: var(--accent);
  }
  .check input:indeterminate + .check-mark::after {
    content: ''; position: absolute; left: 3px; top: 7px;
    width: 10px; height: 2px;
    background: var(--accent-fg);
  }

  .bulk-bar {
    position: fixed; bottom: 24px; left: 50%;
    transform: translateX(-50%) translateY(80px);
    background: var(--surface); border: 1px solid var(--border-strong);
    border-radius: 12px; padding: 10px 12px 10px 18px;
    display: flex; align-items: center; gap: 12px;
    box-shadow: var(--shadow-lg);
    opacity: 0; pointer-events: none;
    transition: all 0.25s cubic-bezier(0.2, 0.8, 0.2, 1);
    z-index: 90;
    max-width: calc(100vw - 32px);
  }
  .bulk-bar.show {
    opacity: 1; pointer-events: auto;
    transform: translateX(-50%) translateY(0);
  }
  .bulk-count { font-size: 13px; font-weight: 500; color: var(--text); }
  .bulk-count strong {
    font-family: 'JetBrains Mono', monospace; font-weight: 600;
  }

  .empty {
    text-align: center; padding: 60px 24px;
    color: var(--text-dim);
    border: 1px dashed var(--border); border-radius: 10px;
    background: var(--surface);
  }
  .empty-icon {
    width: 44px; height: 44px; margin: 0 auto 14px;
    border-radius: 50%; background: var(--bg-elev);
    border: 1px solid var(--border);
    display: flex; align-items: center; justify-content: center;
    color: var(--text-faint);
  }
  .empty-icon svg { width: 18px; height: 18px; }
  .empty h3 { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
  .empty p { font-size: 13px; }

  .settings-card {
    max-width: 640px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 28px;
  }
  .field { margin-bottom: 20px; }
  .field-label {
    display: block; margin-bottom: 6px;
    font-size: 13px; font-weight: 500; color: var(--text);
  }
  .field-hint {
    display: block; margin-bottom: 8px;
    font-size: 12px; color: var(--text-faint);
  }
  .field input[type="text"], .field input[type="number"] {
    width: 100%;
    background: var(--bg); border: 1px solid var(--border);
    color: var(--text); padding: 10px 14px; border-radius: 8px;
    font-family: inherit; font-size: 14px;
    transition: border-color 0.15s ease;
  }
  .field input:focus { outline: none; border-color: var(--text-dim); }

  .toggle-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 0; border-top: 1px solid var(--border); gap: 16px;
  }
  .toggle-row:first-of-type { border-top: none; padding-top: 4px; }
  .toggle-info { flex: 1; }
  .toggle-title { font-size: 14px; font-weight: 500; color: var(--text); }
  .toggle-desc { font-size: 12px; color: var(--text-faint); margin-top: 2px; }

  .switch { position: relative; width: 38px; height: 22px; flex-shrink: 0; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .switch-slider {
    position: absolute; cursor: pointer; inset: 0;
    background: var(--border-strong); border-radius: 999px;
    transition: 0.2s;
  }
  .switch-slider::before {
    content: ''; position: absolute;
    height: 16px; width: 16px; left: 3px; top: 3px;
    background: var(--bg); border-radius: 50%;
    transition: 0.2s;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
  }
  .switch input:checked + .switch-slider { background: var(--accent); }
  .switch input:checked + .switch-slider::before {
    transform: translateX(16px); background: var(--accent-fg);
  }

  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,0.7);
    backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    display: none; align-items: center; justify-content: center;
    z-index: 100; padding: 20px;
  }
  .modal-backdrop.open { display: flex; animation: fadein 0.2s ease; }
  @keyframes fadein { from { opacity: 0; } to { opacity: 1; } }
  .modal {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 14px;
    width: 100%; max-width: 1000px; max-height: 95vh;
    box-shadow: var(--shadow-lg);
    display: flex; flex-direction: column;
    animation: modalin 0.25s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  @keyframes modalin {
    from { opacity: 0; transform: scale(0.98) translateY(8px); }
    to   { opacity: 1; transform: scale(1) translateY(0); }
  }
  .modal-head {
    display: flex; justify-content: space-between; align-items: center;
    padding: 6px 8px 14px;
  }
  .modal-head h3 { font-size: 14px; font-weight: 600; margin: 0; }
  .modal video {
    width: 100%; max-height: calc(95vh - 80px);
    border-radius: 8px; background: black;
  }

  #toast {
    position: fixed; bottom: 24px; left: 50%;
    transform: translateX(-50%) translateY(20px);
    background: var(--surface); color: var(--text);
    padding: 11px 18px; border-radius: 8px;
    border: 1px solid var(--border-strong);
    box-shadow: var(--shadow-lg);
    font-size: 13px; font-weight: 500;
    opacity: 0; pointer-events: none;
    transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
    z-index: 200;
    max-width: calc(100vw - 32px);
    display: flex; align-items: center; gap: 10px;
  }
  #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  #toast .toast-dot {
    width: 6px; height: 6px; border-radius: 50%; background: var(--success);
  }
  #toast.error .toast-dot { background: var(--live); }

  @media (max-width: 720px) {
    .header-inner { padding: 14px 16px; }
    .tabbar { top: 65px; }
    .tabbar-inner { padding: 0 16px; }
    .tab-btn { margin-right: 22px; }
    main { padding: 24px 16px 120px; }

    .add-bar { flex-direction: column; }
    .add-bar input, .add-bar .btn { width: 100%; }

    .streamer-row { flex-wrap: wrap; padding: 14px 16px; }
    .streamer-info { flex: 1 1 calc(100% - 60px); }
    .streamer-status { order: 3; }
    .streamer-actions { flex: 1 1 100%; margin-top: 10px; }
    .streamer-actions .btn { flex: 1; }

    .rec-list-head { display: none; }
    .rec-row {
      grid-template-columns: 30px 1fr;
      gap: 10px 14px; padding: 16px;
    }
    .rec-row .check { align-self: start; margin-top: 2px; }
    .rec-row .rec-cell.duration, .rec-row .rec-cell.size { display: none; }
    .rec-row .rec-cell.date {
      grid-column: 2; font-size: 12px;
    }
    .rec-actions-cell {
      grid-column: 2; justify-content: flex-start; margin-top: 4px;
    }

    .settings-card { padding: 22px; }
  }
</style>
</head>
<body>

<header>
  <div class="header-inner">
    <div class="brand">
      <div class="brand-dot"></div>
      <span>TikTok Recorder</span>
    </div>
    <div class="header-actions">
      <div class="status-pill" id="liveIndicator">
        <div class="dot"></div>
        <span id="headerStatus">0 aktiv</span>
      </div>
      <button class="icon-btn" id="themeToggle" title="Theme wechseln" aria-label="Theme wechseln">
        <svg id="themeIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
      </button>
    </div>
  </div>
</header>

<div class="tabbar">
  <div class="tabbar-inner">
    <button class="tab-btn active" data-tab="streamers">Streamer <span class="tab-count" id="cntStreamers">0</span></button>
    <button class="tab-btn" data-tab="recordings">Aufnahmen <span class="tab-count" id="cntRecordings">0</span></button>
    <button class="tab-btn" data-tab="settings">Einstellungen</button>
  </div>
</div>

<main>

  <div class="tab active" id="tab-streamers">
    <div class="page-head">
      <div>
        <div class="page-title">Streamer</div>
        <div class="page-sub">Verfolgte Accounts mit Auto-Aufnahme</div>
      </div>
      <button class="btn" onclick="checkAll()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 11-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
        Alle prüfen
      </button>
    </div>
    <div class="add-bar">
      <input id="newStreamer" type="text" placeholder="@benutzername hinzufügen…" autocomplete="off" autocapitalize="off" autocorrect="off">
      <button class="btn primary lg" onclick="addStreamer()">Hinzufügen</button>
    </div>
    <div id="streamerList"></div>
  </div>

  <div class="tab" id="tab-recordings">
    <div class="page-head">
      <div>
        <div class="page-title">Aufnahmen</div>
        <div class="page-sub">Alle gespeicherten Streams</div>
      </div>
    </div>
    <div class="toolbar">
      <select class="select" id="filterStreamer" onchange="loadRecordings()">
        <option value="">Alle Streamer</option>
      </select>
      <div class="toolbar-spacer"></div>
      <button class="btn" onclick="loadRecordings()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 11-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
        Aktualisieren
      </button>
    </div>
    <div id="recordingsContainer"></div>
  </div>

  <div class="tab" id="tab-settings">
    <div class="page-head">
      <div>
        <div class="page-title">Einstellungen</div>
        <div class="page-sub">Konfiguration und Verhalten</div>
      </div>
    </div>
    <form class="settings-card" onsubmit="saveSettings(event)">
      <div class="field">
        <label class="field-label">Speicherort</label>
        <span class="field-hint">Verzeichnis, in dem Aufnahmen abgelegt werden</span>
        <input type="text" id="cfgOutputDir">
      </div>
      <div class="field">
        <label class="field-label">Prüfintervall</label>
        <span class="field-hint">Sekunden zwischen den Live-Status-Checks (min. 30)</span>
        <input type="number" id="cfgInterval" min="30" max="3600">
      </div>
      <div class="toggle-row">
        <div class="toggle-info">
          <div class="toggle-title">Auto-Aufnahme</div>
          <div class="toggle-desc">Aufnahmen automatisch starten, wenn ein Streamer live geht</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="cfgAutostart">
          <span class="switch-slider"></span>
        </label>
      </div>
      <div class="toggle-row">
        <div class="toggle-info">
          <div class="toggle-title">Benachrichtigungen</div>
          <div class="toggle-desc">Toast-Meldungen bei Aufnahme-Events anzeigen</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="cfgNotif">
          <span class="switch-slider"></span>
        </label>
      </div>
      <div class="toggle-row">
        <div class="toggle-info">
          <div class="toggle-title">Re-Encode beim Speichern</div>
          <div class="toggle-desc">Robuster gegen Multi-Guest-Streams (höhere CPU-Last)</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="cfgReencode">
          <span class="switch-slider"></span>
        </label>
      </div>
      <div style="margin-top: 24px;">
        <button class="btn primary lg" type="submit" style="width: 100%;">Einstellungen speichern</button>
      </div>
    </form>
  </div>

</main>

<div class="bulk-bar" id="bulkBar">
  <span class="bulk-count"><strong id="bulkCount">0</strong> ausgewählt</span>
  <button class="btn" onclick="clearSelection()">Abbrechen</button>
  <button class="btn danger" onclick="deleteSelected()">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>
    Löschen
  </button>
</div>

<div class="modal-backdrop" id="videoModal" onclick="if(event.target===this)closeVideo()">
  <div class="modal">
    <div class="modal-head">
      <h3 id="videoTitle"></h3>
      <button class="icon-btn" onclick="closeVideo()" aria-label="Schließen">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
      </button>
    </div>
    <video id="videoPlayer" controls playsinline></video>
  </div>
</div>

<div id="toast"><span class="toast-dot"></span><span id="toastText"></span></div>

<script>
const root = document.documentElement;
const savedTheme = localStorage.getItem('theme');
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
const initialTheme = savedTheme || (prefersDark ? 'dark' : 'light');
root.setAttribute('data-theme', initialTheme);
updateThemeIcon();

document.getElementById('themeToggle').onclick = () => {
  const current = root.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  updateThemeIcon();
};
function updateThemeIcon() {
  const isDark = root.getAttribute('data-theme') === 'dark';
  const icon = document.getElementById('themeIcon');
  if (isDark) {
    icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
  } else {
    icon.innerHTML = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>';
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}
function toast(msg, type = 'success') {
  const el = document.getElementById('toast');
  document.getElementById('toastText').textContent = msg;
  el.className = type === 'error' ? 'error show' : 'show';
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => { el.className = ''; }, 3200);
}
function fmtDuration(s) {
  if (!s) return '—';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
  if (h) return `${h}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
  return `${m}:${String(sec).padStart(2,'0')}`;
}
function fmtSize(b) {
  if (!b) return '—';
  const u = ['B','KB','MB','GB','TB']; let i = 0;
  while (b >= 1024 && i < u.length-1) { b /= 1024; i++; }
  return b.toFixed(b < 10 ? 1 : 0) + ' ' + u[i];
}
function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
}
function initials(name) { return name.slice(0, 2).toUpperCase(); }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'recordings') loadRecordings();
    if (btn.dataset.tab === 'settings') loadSettings();
    clearSelection();
  };
});

async function loadStreamers() {
  try {
    const list = await api('/api/streamers');
    const container = document.getElementById('streamerList');
    document.getElementById('cntStreamers').textContent = list.length;
    if (list.length === 0) {
      container.innerHTML = `
        <div class="empty">
          <div class="empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 11h-6M19 8v6"/></svg>
          </div>
          <h3>Noch keine Streamer</h3>
          <p>Füge oben einen TikTok-Benutzernamen hinzu, um zu starten.</p>
        </div>`;
      return;
    }
    container.innerHTML = '<div class="streamer-list">' + list.map(s => `
      <div class="streamer-row ${s.recording ? 'live' : ''}">
        <div class="streamer-avatar">${initials(s.username)}</div>
        <div class="streamer-info">
          <div class="streamer-name">@${escapeHtml(s.username)}</div>
          <div class="streamer-meta">seit ${fmtDate(s.added_at)}</div>
        </div>
        <div class="streamer-status">
          <div class="dot"></div>
          ${s.recording ? 'LIVE' : 'OFFLINE'}
        </div>
        <div class="streamer-actions">
          ${s.recording ? `<button class="btn split" onclick="splitRecording('${escapeHtml(s.username)}')">Splitten</button>` : ''}
          <button class="btn" onclick="checkStreamer('${escapeHtml(s.username)}')">Prüfen</button>
          <button class="btn" onclick="viewStreamerRecordings('${escapeHtml(s.username)}')">Aufnahmen</button>
          <button class="icon-btn" onclick="removeStreamer('${escapeHtml(s.username)}')" title="Entfernen">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      </div>`).join('') + '</div>';

    const active = list.filter(s => s.recording).length;
    document.getElementById('headerStatus').textContent = `${active} aktiv`;
    document.getElementById('liveIndicator').className =
      'status-pill' + (active > 0 ? ' active' : '');
  } catch (e) { console.error(e); }
}

async function addStreamer() {
  const input = document.getElementById('newStreamer');
  const username = input.value.trim();
  if (!username) return;
  try {
    const res = await api('/api/streamers', { method: 'POST', body: { username } });
    if (res.ok) {
      input.value = '';
      toast(`@${username.replace(/^@/,'')} hinzugefügt`);
      loadStreamers();
    } else {
      toast(res.error || 'Fehler beim Hinzufügen', 'error');
    }
  } catch { toast('Fehler beim Hinzufügen', 'error'); }
}
async function removeStreamer(username) {
  if (!confirm(`@${username} wirklich entfernen?`)) return;
  await api('/api/streamers/' + encodeURIComponent(username), { method: 'DELETE' });
  toast(`@${username} entfernt`);
  loadStreamers();
}
async function checkStreamer(username) {
  await api('/api/streamers/' + encodeURIComponent(username) + '/check', { method: 'POST' });
  toast(`Prüfe @${username} …`);
  setTimeout(loadStreamers, 2000);
}
async function checkAll() {
  await api('/api/streamers/check-all', { method: 'POST' });
  toast('Prüfe alle Streamer …');
  setTimeout(loadStreamers, 2000);
}
async function splitRecording(username) {
  if (!confirm(`Aufnahme von @${username} splitten?

Die aktuelle Datei wird gespeichert. Eine neue Aufnahme startet direkt danach.`)) return;
  try {
    const res = await api('/api/streamers/' + encodeURIComponent(username) + '/split', { method: 'POST' });
    if (res.ok) {
      toast(`@${username} gesplittet`);
      loadStreamers(); loadRecordings();
    } else { toast('Split fehlgeschlagen', 'error'); }
  } catch { toast('Split fehlgeschlagen', 'error'); }
}
function viewStreamerRecordings(username) {
  document.querySelector('[data-tab="recordings"]').click();
  setTimeout(() => {
    document.getElementById('filterStreamer').value = username;
    loadRecordings();
  }, 100);
}

let selectedIds = new Set();
let allRecIds = [];

async function loadRecordings() {
  try {
    const streamers = await api('/api/streamers');
    const sel = document.getElementById('filterStreamer');
    const current = sel.value;
    sel.innerHTML = '<option value="">Alle Streamer</option>' +
      streamers.map(s => `<option value="${escapeHtml(s.username)}">@${escapeHtml(s.username)}</option>`).join('');
    sel.value = current;

    const filter = sel.value;
    const url = filter ? '/api/recordings?username=' + encodeURIComponent(filter) : '/api/recordings';
    const recs = await api(url);
    document.getElementById('cntRecordings').textContent = recs.length;
    allRecIds = recs.map(r => r.id);

    const container = document.getElementById('recordingsContainer');
    if (recs.length === 0) {
      container.innerHTML = `
        <div class="empty">
          <div class="empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
          </div>
          <h3>Noch keine Aufnahmen</h3>
          <p>Sobald ein Streamer live geht, erscheinen die Aufnahmen hier.</p>
        </div>`;
      clearSelection();
      return;
    }

    container.innerHTML = `
      <div class="rec-list">
        <div class="rec-list-head">
          <label class="check">
            <input type="checkbox" id="selectAll" onchange="toggleSelectAll(this.checked)">
            <span class="check-mark"></span>
          </label>
          <div>Streamer / Datei</div>
          <div>Datum</div>
          <div>Dauer</div>
          <div>Größe</div>
          <div></div>
        </div>
        ${recs.map(r => `
          <div class="rec-row ${selectedIds.has(r.id) ? 'selected' : ''}" data-id="${r.id}" onclick="onRowClick(event, ${r.id})">
            <label class="check" onclick="event.stopPropagation()">
              <input type="checkbox" ${selectedIds.has(r.id) ? 'checked' : ''} onchange="toggleSelect(${r.id}, this.checked)">
              <span class="check-mark"></span>
            </label>
            <div class="rec-info">
              <div class="rec-streamer">@${escapeHtml(r.username)}</div>
              <div class="rec-file">${escapeHtml(r.filepath.split(/[\/]/).pop())}</div>
            </div>
            <div class="rec-cell date">${fmtDate(r.started_at)}</div>
            <div class="rec-cell duration">${fmtDuration(r.duration_seconds)}</div>
            <div class="rec-cell size">${fmtSize(r.file_size)}</div>
            <div class="rec-actions-cell" onclick="event.stopPropagation()">
              <button class="icon-btn" onclick="playVideo(${r.id}, '${escapeHtml(r.username)}')" title="Abspielen">
                <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>
              </button>
              <a href="/api/recordings/${r.id}/video?download=1" download>
                <button class="icon-btn" title="Download">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                </button>
              </a>
            </div>
          </div>`).join('')}
      </div>`;
    updateBulkBar();
    updateSelectAllState();
  } catch (e) { console.error(e); }
}

function onRowClick(event, id) {
  if (selectedIds.size > 0) {
    const cb = event.currentTarget.querySelector('input[type="checkbox"]');
    cb.checked = !cb.checked;
    toggleSelect(id, cb.checked);
  } else {
    const username = event.currentTarget.querySelector('.rec-streamer').textContent.replace('@', '');
    playVideo(id, username);
  }
}
function toggleSelect(id, checked) {
  if (checked) selectedIds.add(id);
  else selectedIds.delete(id);
  const row = document.querySelector(`.rec-row[data-id="${id}"]`);
  if (row) row.classList.toggle('selected', checked);
  updateBulkBar();
  updateSelectAllState();
}
function toggleSelectAll(checked) {
  if (checked) allRecIds.forEach(id => selectedIds.add(id));
  else selectedIds.clear();
  document.querySelectorAll('.rec-row').forEach(row => {
    const cb = row.querySelector('input[type="checkbox"]');
    if (cb) cb.checked = checked;
    row.classList.toggle('selected', checked);
  });
  updateBulkBar();
}
function updateSelectAllState() {
  const cb = document.getElementById('selectAll');
  if (!cb) return;
  if (selectedIds.size === 0) {
    cb.checked = false; cb.indeterminate = false;
  } else if (selectedIds.size === allRecIds.length) {
    cb.checked = true; cb.indeterminate = false;
  } else {
    cb.checked = false; cb.indeterminate = true;
  }
}
function clearSelection() {
  selectedIds.clear();
  document.querySelectorAll('.rec-row.selected').forEach(r => r.classList.remove('selected'));
  document.querySelectorAll('.rec-row input[type="checkbox"]').forEach(c => c.checked = false);
  const all = document.getElementById('selectAll');
  if (all) { all.checked = false; all.indeterminate = false; }
  updateBulkBar();
}
function updateBulkBar() {
  const bar = document.getElementById('bulkBar');
  document.getElementById('bulkCount').textContent = selectedIds.size;
  bar.classList.toggle('show', selectedIds.size > 0);
}

async function deleteSelected() {
  const ids = [...selectedIds];
  if (ids.length === 0) return;
  if (!confirm(`${ids.length} Aufnahme${ids.length === 1 ? '' : 'n'} löschen?

Die Videodateien bleiben auf der Platte erhalten.`)) return;
  try {
    await api('/api/recordings/delete-bulk', { method: 'POST', body: { ids } });
    toast(`${ids.length} Aufnahme${ids.length === 1 ? '' : 'n'} gelöscht`);
    clearSelection();
    loadRecordings();
  } catch {
    toast('Fehler beim Löschen', 'error');
  }
}

function playVideo(id, username) {
  document.getElementById('videoTitle').textContent = '@' + username;
  const vid = document.getElementById('videoPlayer');
  vid.src = '/api/recordings/' + id + '/video';
  document.getElementById('videoModal').classList.add('open');
  vid.play().catch(() => {});
}
function closeVideo() {
  const vid = document.getElementById('videoPlayer');
  vid.pause(); vid.src = '';
  document.getElementById('videoModal').classList.remove('open');
}

async function loadSettings() {
  const cfg = await api('/api/config');
  document.getElementById('cfgOutputDir').value = cfg.output_dir;
  document.getElementById('cfgInterval').value = cfg.check_interval;
  document.getElementById('cfgAutostart').checked = cfg.autostart_recording;
  document.getElementById('cfgNotif').checked = cfg.notifications_enabled;
  document.getElementById('cfgReencode').checked = cfg.reencode_on_remux;
}
async function saveSettings(e) {
  e.preventDefault();
  const body = {
    output_dir: document.getElementById('cfgOutputDir').value,
    check_interval: parseInt(document.getElementById('cfgInterval').value),
    autostart_recording: document.getElementById('cfgAutostart').checked,
    notifications_enabled: document.getElementById('cfgNotif').checked,
    reencode_on_remux: document.getElementById('cfgReencode').checked,
  };
  await api('/api/config', { method: 'POST', body });
  toast('Einstellungen gespeichert');
}

document.getElementById('newStreamer').addEventListener('keypress', e => {
  if (e.key === 'Enter') addStreamer();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (document.getElementById('videoModal').classList.contains('open')) closeVideo();
    else if (selectedIds.size > 0) clearSelection();
  }
});

loadStreamers();
setInterval(loadStreamers, 5000);
setInterval(() => {
  if (document.getElementById('tab-recordings').classList.contains('active') && selectedIds.size === 0) {
    loadRecordings();
  }
}, 10000);
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Flask-App-Factory
# --------------------------------------------------------------------------- #

def create_app(
    manager: RecorderManager,
    auth_user: Optional[str] = None,
    auth_pass: Optional[str] = None,
) -> Flask:
    """
    Erstellt die Flask-App und bindet alle Routen an den Manager.

    Wenn auth_user und auth_pass gesetzt sind, werden alle Routen mit
    HTTP-Basic-Auth geschützt.
    """
    global _manager
    _manager = manager

    app = Flask(__name__)

    # Flask/Werkzeug-Logger leiser stellen
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.logger.setLevel(logging.WARNING)

    # ---------- Auth ----------
    auth_enabled = bool(auth_user and auth_pass)

    def check_auth(user: str, password: str) -> bool:
        # secrets.compare_digest schützt vor Timing-Attacken
        return (
            secrets.compare_digest(user, auth_user or "")
            and secrets.compare_digest(password, auth_pass or "")
        )

    def require_auth(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not auth_enabled:
                return f(*args, **kwargs)
            auth = request.authorization
            if not auth or not check_auth(auth.username or "", auth.password or ""):
                return Response(
                    "Authentifizierung erforderlich",
                    401,
                    {"WWW-Authenticate": 'Basic realm="TikTok Recorder"'},
                )
            return f(*args, **kwargs)
        return wrapper

    # ---------- Haupt-HTML ----------

    @app.route("/")
    @require_auth
    def index():
        return Response(HTML_PAGE, mimetype="text/html")

    # ---------- Streamer ----------

    @app.route("/api/streamers", methods=["GET"])
    @require_auth
    def api_list_streamers():
        streamers = db.list_streamers()
        result = []
        for s in streamers:
            result.append({
                "username": s["username"],
                "added_at": s["added_at"],
                "recording": _manager.is_recording(s["username"]),
            })
        return jsonify(result)

    @app.route("/api/streamers", methods=["POST"])
    @require_auth
    def api_add_streamer():
        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip().lstrip("@")
        if not username:
            return jsonify({"ok": False, "error": "Benutzername erforderlich"}), 400
        if db.add_streamer(username):
            _manager.check_now(username)
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "Existiert bereits oder ungültig"}), 400

    @app.route("/api/streamers/<username>", methods=["DELETE"])
    @require_auth
    def api_remove_streamer(username):
        db.remove_streamer(username)
        return jsonify({"ok": True})

    @app.route("/api/streamers/<username>/check", methods=["POST"])
    @require_auth
    def api_check_streamer(username):
        _manager.check_now(username)
        return jsonify({"ok": True})

    @app.route("/api/streamers/check-all", methods=["POST"])
    @require_auth
    def api_check_all():
        for s in db.list_streamers():
            _manager.check_now(s["username"])
        return jsonify({"ok": True})

    @app.route("/api/streamers/<username>/split", methods=["POST"])
    @require_auth
    def api_split(username):
        ok = _manager.split_recording(username)
        return jsonify({"ok": ok})

    # ---------- Aufnahmen ----------

    @app.route("/api/recordings", methods=["GET"])
    @require_auth
    def api_list_recordings():
        username = request.args.get("username") or None
        recs = db.list_recordings(username)
        # Nur fertig remuxte Aufnahmen anzeigen — .ts-Dateien sind entweder
        # gerade in Aufnahme oder fehlgeschlagene Remuxe und sollen die
        # Übersicht nicht verschmutzen
        recs = [r for r in recs if r["filepath"].lower().endswith(".mp4")]
        return jsonify(recs)

    @app.route("/api/recordings/<int:rec_id>", methods=["DELETE"])
    @require_auth
    def api_delete_recording(rec_id):
        db.delete_recording(rec_id)
        return jsonify({"ok": True})

    @app.route("/api/recordings/delete-bulk", methods=["POST"])
    @require_auth
    def api_delete_bulk():
        """Löscht mehrere Aufnahme-Einträge anhand einer Liste von IDs."""
        data = request.get_json(silent=True) or {}
        ids = data.get("ids") or []
        if not isinstance(ids, list):
            return jsonify({"ok": False, "error": "ids muss eine Liste sein"}), 400
        deleted = 0
        for rec_id in ids:
            try:
                db.delete_recording(int(rec_id))
                deleted += 1
            except (ValueError, TypeError):
                continue
        return jsonify({"ok": True, "deleted": deleted})

    @app.route("/api/recordings/<int:rec_id>/video")
    @require_auth
    def api_stream_video(rec_id):
        """Liefert die Videodatei aus – mit Range-Requests für das <video>-Element."""
        recs = [r for r in db.list_recordings() if r["id"] == rec_id]
        if not recs:
            abort(404)
        path = Path(recs[0]["filepath"])
        if not path.exists():
            abort(404)
        # MIME dynamisch bestimmen, falls doch mal eine .ts-Datei übrigbleibt
        suffix = path.suffix.lower()
        mimetype = {
            ".mp4": "video/mp4",
            ".ts":  "video/mp2t",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
        }.get(suffix, "application/octet-stream")
        as_attachment = request.args.get("download") == "1"
        return send_file(
            str(path),
            mimetype=mimetype,
            conditional=True,            # ermöglicht Seeking im Browser
            as_attachment=as_attachment,
            download_name=path.name,
        )

    # ---------- Config ----------

    @app.route("/api/config", methods=["GET"])
    @require_auth
    def api_get_config():
        return jsonify(load_config())

    @app.route("/api/config", methods=["POST"])
    @require_auth
    def api_set_config():
        data = request.get_json(silent=True) or {}
        cfg = load_config()
        for key in (
            "output_dir", "check_interval", "notifications_enabled",
            "dark_mode", "autostart_recording", "video_format",
            "reencode_on_remux",
        ):
            if key in data:
                cfg[key] = data[key]
        save_config(cfg)
        return jsonify({"ok": True})

    return app


# --------------------------------------------------------------------------- #
# Server-Start
# --------------------------------------------------------------------------- #

def run_web(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    auth_user: Optional[str] = None,
    auth_pass: Optional[str] = None,
) -> None:
    """
    Startet den Webserver und öffnet optional den Standard-Browser.

    :param host: Host-Adresse (127.0.0.1 = nur lokal, 0.0.0.0 = von außen erreichbar)
    :param port: TCP-Port
    :param open_browser: Browser nach 1s automatisch öffnen (auf Servern: False)
    :param auth_user: Benutzername für HTTP-Basic-Auth (optional)
    :param auth_pass: Passwort für HTTP-Basic-Auth (optional)
    """
    manager = RecorderManager()
    manager.start()

    # Auf Server-Bind ohne Auth: Warnung ausgeben
    if host != "127.0.0.1" and not (auth_user and auth_pass):
        log.warning(
            "⚠ Server lauscht auf %s OHNE Authentifizierung! "
            "Setze TTR_AUTH_USER und TTR_AUTH_PASS, um die App zu schützen.",
            host,
        )

    app = create_app(manager, auth_user=auth_user, auth_pass=auth_pass)

    display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    url = f"http://{display_host}:{port}"
    log.info("Webserver läuft auf %s (bind=%s)", url, host)
    print(f"\n🎬 TikTok Live Recorder läuft auf: {url}")
    if auth_user:
        print(f"   🔐 Auth aktiv (Benutzer: {auth_user})")
    print()

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        log.info("Beende Server …")
    finally:
        manager.stop()
