from contextlib import contextmanager
import json
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import AI_NOTES_CHUNK_INTERVAL_SECONDS, SPOTIFY_CLIENT_ID, STREAM_TTS_MODE
from ai_notes.api.router import router as ai_notes_router
from app.conversation.tts_jobs import get_tts_job
from app.orchestrator.intelligence import IntelligenceOrchestrator
from app.orchestrator.stream_pipeline import (
    stream_ndjson_response,
    stream_query,
    stream_voice_query,
)
from app.tools.spotify_client import SpotifyClient, SpotifyApiError, SpotifyAuthRequired
from app.utils.pipeline_log import (
    PipelineLogger,
    reset_pipeline_logger,
    set_pipeline_logger,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI()
app.include_router(ai_notes_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
orchestrator = IntelligenceOrchestrator()
spotify_client = SpotifyClient()


class ProfileRequest(BaseModel):
    name: str = ""
    age: str = ""
    dob: str = ""
    height: str = ""
    weight: str = ""


class TranscriptRequest(BaseModel):
    transcript: str
    intent: str | None = None
    chat_id: str | None = None
    user_id: str | None = None
    profile: ProfileRequest | None = None


def _profile_payload(profile: ProfileRequest | None) -> dict | None:
    if profile is None:
        return None

    return profile.model_dump()


class CreateChatRequest(BaseModel):
    title: str = "New chat"


class TtsRequest(BaseModel):
    text: str
    transcript: str = ""


class SpotifyPlayRequest(BaseModel):
    uri: str
    device_id: str


@contextmanager
def pipeline_session():
    pipeline_logger = PipelineLogger()
    token = set_pipeline_logger(pipeline_logger)
    try:
        yield pipeline_logger
    finally:
        reset_pipeline_logger(token)


@app.get("/", response_class=HTMLResponse)
def home():
    return (
        PLAYGROUND_HTML.replace("__STREAM_TTS_MODE__", STREAM_TTS_MODE)
        .replace(
            "__AI_NOTES_CHUNK_INTERVAL__",
            str(AI_NOTES_CHUNK_INTERVAL_SECONDS),
        )
    )


PLAYGROUND_HTML = """
<!doctype html>
<html>
<head>
  <title>Luvio Playground</title>
  <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/static/favicon.svg">
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f7f8;
      --panel: #ffffff;
      --text: #202123;
      --muted: #6b7280;
      --border: #d9d9e3;
      --user: #202123;
      --assistant: #ffffff;
      --accent: #10a37f;
      --accent-strong: #0d8f6f;
      --log-bg: #111827;
      --log-text: #e5e7eb;
      --sidebar: #f0f0f5;
    }

    * { box-sizing: border-box; }

    html, body {
      height: 100%;
      overflow: hidden;
    }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    .app {
      display: grid;
      grid-template-columns: 260px 1fr 0;
      height: 100vh;
      overflow: hidden;
      transition: grid-template-columns 0.25s ease;
    }

    .app.logs-open {
      grid-template-columns: 260px 1fr 380px;
    }

    .chats-panel {
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
      background: var(--sidebar);
      border-right: 1px solid var(--border);
    }

    .chats-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 14px 12px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }

    .chats-header h2 {
      margin: 0;
      font-size: 14px;
      font-weight: 650;
    }

    .chats-list {
      flex: 1;
      overflow-y: auto;
      overscroll-behavior: contain;
      padding: 8px;
    }

    .chat-item {
      width: 100%;
      text-align: left;
      padding: 10px 12px;
      margin-bottom: 4px;
      border: 1px solid transparent;
      border-radius: 8px;
      background: transparent;
      color: var(--text);
      font: inherit;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .chat-item:hover { background: #e8e8ee; }
    .chat-item.active {
      background: #fff;
      border-color: var(--border);
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    }

    .chat-item-row {
      display: flex;
      align-items: center;
      gap: 4px;
      margin-bottom: 4px;
    }

    .chat-item-row .chat-item {
      flex: 1;
      margin-bottom: 0;
    }

    .chat-delete {
      min-width: 32px;
      min-height: 32px;
      padding: 0;
      background: transparent;
      color: #9ca3af;
      font-size: 16px;
      line-height: 1;
    }

    .chat-delete:hover {
      background: #fee2e2;
      color: #b42318;
    }

    .profile-wrap {
      position: relative;
    }

    .profile-button {
      width: 38px;
      min-width: 38px;
      height: 38px;
      min-height: 38px;
      padding: 0;
      border-radius: 999px;
      background: #202123;
      color: #fff;
      font-size: 13px;
      font-weight: 700;
    }

    .profile-menu {
      display: none;
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      min-width: 180px;
      background: #fff;
      border: 1px solid var(--border);
      border-radius: 10px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12);
      overflow: hidden;
      z-index: 20;
    }

    .profile-menu.open { display: block; }

    .profile-menu button {
      width: 100%;
      min-height: 40px;
      border-radius: 0;
      background: #fff;
      color: var(--text);
      text-align: left;
      padding: 0 14px;
      font-weight: 500;
    }

    .profile-menu button:hover { background: #f3f4f6; }

    .now-playing {
      display: none;
      margin-top: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: #ecfdf5;
      border: 1px solid #a7f3d0;
      font-size: 13px;
      color: #065f46;
    }

    .now-playing.active { display: block; }

    .now-playing-card {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .now-playing-art {
      width: 64px;
      height: 64px;
      border-radius: 8px;
      object-fit: cover;
      background: #d1fae5;
      flex-shrink: 0;
    }

    .now-playing-meta {
      flex: 1;
      min-width: 0;
    }

    .now-playing-title {
      font-size: 14px;
      font-weight: 650;
      color: #064e3b;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .now-playing-artist {
      font-size: 13px;
      color: #047857;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .now-playing-status {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-top: 6px;
      font-size: 12px;
      font-weight: 600;
      color: #059669;
    }

    .now-playing-status.paused { color: #6b7280; }

    .now-playing-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      animation: pulse 1.2s ease-in-out infinite;
    }

    .now-playing-status.paused .now-playing-dot {
      animation: none;
      background: #9ca3af;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.45; transform: scale(0.85); }
    }

    .now-playing-toggle {
      width: 42px;
      height: 42px;
      min-width: 42px;
      padding: 0;
      border-radius: 50%;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: -0.5px;
      flex-shrink: 0;
    }

    .now-playing iframe {
      display: block;
      width: 100%;
      border: 0;
      border-radius: 12px;
    }

    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.35);
      z-index: 30;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }

    .modal-backdrop.open { display: flex; }

    .modal {
      width: min(420px, 100%);
      background: #fff;
      border-radius: 12px;
      border: 1px solid var(--border);
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.18);
      padding: 20px;
    }

    .modal h3 {
      margin: 0 0 16px;
      font-size: 18px;
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 12px;
    }

    .field label {
      font-size: 13px;
      color: var(--muted);
    }

    .field input {
      min-height: 40px;
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      font: inherit;
    }

    .modal-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 8px;
    }

    .shell {
      position: relative;
      display: grid;
      grid-template-rows: auto 1fr auto;
      height: 100vh;
      overflow: hidden;
      min-width: 0;
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 20px;
      background: var(--panel);
      border-bottom: 1px solid var(--border);
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    h1 {
      margin: 0;
      font-size: 17px;
      font-weight: 650;
    }

    .status {
      min-height: 20px;
      color: var(--muted);
      font-size: 13px;
      text-align: right;
    }

    .chat-wrap {
      overflow-y: auto;
      overscroll-behavior: contain;
      min-height: 0;
    }

    .chat {
      width: min(920px, 100%);
      margin: 0 auto;
      padding: 24px 16px 32px;
    }

    .empty {
      display: grid;
      place-items: center;
      min-height: 52vh;
      color: var(--muted);
      text-align: center;
      line-height: 1.5;
    }

    .message {
      display: flex;
      margin: 18px 0;
    }

    .message.user { justify-content: flex-end; }

    .bubble {
      max-width: min(680px, 86vw);
      padding: 13px 15px;
      border: 1px solid var(--border);
      border-radius: 8px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .user .bubble {
      background: var(--user);
      color: #fff;
      border-color: var(--user);
    }

    .assistant .bubble { background: var(--assistant); }

    .composer-wrap {
      padding: 16px;
      background: linear-gradient(180deg, rgba(247, 247, 248, 0), var(--bg) 35%);
      border-top: 1px solid var(--border);
    }

    .composer {
      display: flex;
      flex-direction: column;
      gap: 10px;
      width: min(920px, 100%);
      margin: 0 auto;
      padding: 10px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08);
    }

    .composer-row {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .text-input {
      flex: 1;
      min-height: 42px;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      font: inherit;
      font-size: 14px;
      resize: none;
    }

    .text-input:focus {
      outline: 2px solid rgba(16, 163, 127, 0.25);
      border-color: var(--accent);
    }

    .hint {
      flex: 1;
      color: var(--muted);
      font-size: 14px;
      padding-left: 4px;
    }

    .meeting-banner {
      display: none;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border-radius: 8px;
      background: #fff7ed;
      border: 1px solid #fdba74;
      color: #9a3412;
      font-size: 13px;
      font-weight: 600;
    }

    .meeting-banner.active {
      display: flex;
    }

    .meeting-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: #ef4444;
      animation: pulse 1.2s infinite;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.35; }
    }

    button.meeting-active {
      background: #ea580c;
    }

    button.meeting-active:hover {
      background: #c2410c;
    }

    button {
      min-width: 42px;
      min-height: 42px;
      border: 0;
      border-radius: 8px;
      background: var(--accent);
      color: white;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
    }

    button:hover { background: var(--accent-strong); }
    button:disabled { cursor: not-allowed; background: #c7c7d1; }

    .secondary {
      width: auto;
      padding: 0 13px;
      background: #ececf1;
      color: var(--text);
    }

    .secondary:hover { background: #e2e2e8; }
    .secondary.active { background: #dbeafe; color: #1d4ed8; }

    .recording { color: #b42318; }

    .logs-panel {
      border-left: 1px solid var(--border);
      background: var(--log-bg);
      color: var(--log-text);
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }

    .logs-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      border-bottom: 1px solid #374151;
      flex-shrink: 0;
    }

    .logs-header h2 {
      margin: 0;
      font-size: 14px;
      font-weight: 650;
    }

    .logs-body {
      flex: 1;
      overflow-y: auto;
      overscroll-behavior: contain;
      min-height: 0;
      -webkit-overflow-scrolling: touch;
    }

    .logs-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 12px;
    }

    .log-empty {
      color: #9ca3af;
      font-size: 13px;
      line-height: 1.5;
      padding: 12px;
    }

    .log-entry {
      border: 1px solid #374151;
      border-radius: 8px;
      padding: 10px 12px;
      background: #1f2937;
      animation: fadeIn 0.2s ease;
      flex-shrink: 0;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .log-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 6px;
    }

    .log-step {
      font-size: 12px;
      font-weight: 650;
      color: #93c5fd;
    }

    .log-status {
      font-size: 11px;
      font-weight: 650;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: 999px;
    }

    .log-status.started { background: #78350f; color: #fde68a; }
    .log-status.completed { background: #064e3b; color: #6ee7b7; }
    .log-status.error { background: #7f1d1d; color: #fecaca; }

    .log-message {
      font-size: 13px;
      line-height: 1.45;
      margin-bottom: 6px;
    }

    .log-time {
      font-size: 11px;
      color: #9ca3af;
    }

    .log-details {
      margin-top: 8px;
      padding: 8px;
      border-radius: 6px;
      background: #111827;
      font-size: 11px;
      line-height: 1.4;
      color: #d1d5db;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .live-voice-btn {
      width: 40px;
      height: 40px;
      padding: 0;
      border: none;
      border-radius: 50%;
      background: #111;
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      flex-shrink: 0;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.22);
      transition: transform 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
    }

    .live-voice-btn:hover:not(:disabled) {
      transform: scale(1.05);
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.28);
    }

    .live-voice-btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }

    .live-voice-btn.active {
      background: #10a37f;
    }

    .live-voice-btn .wave {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 2.5px;
    }

    .live-voice-btn .wave span {
      width: 2.5px;
      border-radius: 999px;
      background: #111;
      display: block;
    }

    .live-voice-btn .wave span:nth-child(1) { height: 8px; }
    .live-voice-btn .wave span:nth-child(2) { height: 16px; }
    .live-voice-btn .wave span:nth-child(3) { height: 12px; }
    .live-voice-btn .wave span:nth-child(4) { height: 8px; }

    /* Live voice dock: chats stay fully visible and scrollable. */
    .voice-overlay {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      top: auto;
      z-index: 25;
      display: none;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      gap: 10px;
      padding: 12px 16px 10px;
      pointer-events: none;
      background: linear-gradient(
        to top,
        rgba(247, 247, 248, 0.96) 0%,
        rgba(247, 247, 248, 0.82) 55%,
        rgba(247, 247, 248, 0) 100%
      );
    }

    .voice-overlay.active {
      display: flex;
    }

    .voice-orb-wrap {
      position: relative;
      width: 112px;
      height: 112px;
      display: grid;
      place-items: center;
      pointer-events: auto;
    }

    .voice-orb-ring {
      position: absolute;
      inset: 0;
      border-radius: 50%;
      border: 2px solid rgba(16, 163, 127, 0.28);
      transform: scale(0.92);
      opacity: 0.45;
      transition: transform 0.2s ease, opacity 0.2s ease, border-color 0.2s ease;
    }

    .voice-orb {
      position: relative;
      width: 72%;
      height: 72%;
      border-radius: 50%;
      background: #111;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
      transition: transform 0.12s ease;
    }

    .voice-orb .bar {
      width: 4px;
      border-radius: 999px;
      background: #fff;
      transition: height 0.08s linear;
    }

    .voice-orb .bar:nth-child(1) { height: 12px; }
    .voice-orb .bar:nth-child(2) { height: 24px; }
    .voice-orb .bar:nth-child(3) { height: 18px; }
    .voice-orb .bar:nth-child(4) { height: 12px; }

    .voice-overlay[data-state="listening"] .voice-orb-ring {
      animation: orb-breathe 2.4s ease-in-out infinite;
    }

    .voice-overlay[data-state="user-speaking"] .voice-orb-ring,
    .voice-overlay[data-state="thinking"] .voice-orb-ring,
    .voice-overlay[data-state="speaking"] .voice-orb-ring {
      animation: orb-throb 1.1s ease-in-out infinite;
      border-color: rgba(16, 163, 127, 0.65);
      opacity: 0.8;
    }

    .voice-overlay[data-state="thinking"] .voice-orb .bar {
      animation: bar-pulse 0.9s ease-in-out infinite;
    }

    .voice-overlay[data-state="thinking"] .voice-orb .bar:nth-child(2) {
      animation-delay: 0.12s;
    }

    .voice-overlay[data-state="thinking"] .voice-orb .bar:nth-child(3) {
      animation-delay: 0.24s;
    }

    .voice-overlay[data-state="thinking"] .voice-orb .bar:nth-child(4) {
      animation-delay: 0.36s;
    }

    .voice-overlay[data-state="speaking"] .voice-orb .bar {
      animation: bar-speak 0.7s ease-in-out infinite;
    }

    .voice-overlay[data-state="speaking"] .voice-orb .bar:nth-child(2) {
      animation-delay: 0.1s;
    }

    .voice-overlay[data-state="speaking"] .voice-orb .bar:nth-child(3) {
      animation-delay: 0.2s;
    }

    .voice-overlay[data-state="speaking"] .voice-orb .bar:nth-child(4) {
      animation-delay: 0.3s;
    }

    .voice-overlay-label {
      color: var(--muted);
      font-size: 13px;
      font-weight: 550;
      letter-spacing: 0.01em;
      text-align: center;
      min-height: 1.3em;
      pointer-events: none;
    }

    .voice-stop-btn {
      width: 40px;
      height: 40px;
      border-radius: 50%;
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      pointer-events: auto;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
      transition: background 0.15s ease, transform 0.15s ease;
    }

    .voice-stop-btn:hover {
      background: #f3f4f6;
      transform: scale(1.06);
    }

    .voice-stop-btn svg {
      width: 16px;
      height: 16px;
    }

    .shell.live-active .chat-wrap {
      padding-bottom: 168px;
    }

    .shell.live-active .composer-wrap {
      opacity: 0.35;
      pointer-events: none;
    }

    @keyframes orb-breathe {
      0%, 100% { transform: scale(0.92); opacity: 0.35; }
      50% { transform: scale(1.04); opacity: 0.7; }
    }

    @keyframes orb-throb {
      0%, 100% { transform: scale(0.96); opacity: 0.5; }
      50% { transform: scale(1.12); opacity: 0.95; }
    }

    @keyframes bar-pulse {
      0%, 100% { transform: scaleY(0.55); opacity: 0.55; }
      50% { transform: scaleY(1); opacity: 1; }
    }

    @keyframes bar-speak {
      0%, 100% { transform: scaleY(0.45); }
      50% { transform: scaleY(1.15); }
    }
  </style>
</head>
<body>
  <div class="app" id="app">
    <aside class="chats-panel">
      <div class="chats-header">
        <h2>Chats</h2>
        <button class="secondary" id="newChat">New</button>
      </div>
      <div class="chats-list" id="chatsList"></div>
    </aside>

    <div class="shell" id="shell">
      <header>
        <h1>Luvio Playground</h1>
        <div class="header-actions">
          <button class="secondary" id="logsToggle">Logs</button>
          <div class="status" id="status">Ready</div>
          <div class="profile-wrap">
            <button class="profile-button" id="profileButton">G</button>
            <div class="profile-menu" id="profileMenu">
              <button id="openPersonalisation">Personalisation</button>
            </div>
          </div>
        </div>
      </header>

      <main class="chat-wrap" id="chatWrap">
        <div class="chat" id="chat">
          <div class="empty" id="empty">
            <div>
              <strong>Ask Luvio with voice or text.</strong><br>
              Type a message, use Start / Stop, or tap the voice circle for live talk.
            </div>
          </div>
        </div>
      </main>

      <div class="voice-overlay" id="voiceOverlay" aria-hidden="true">
        <div class="voice-orb-wrap">
          <div class="voice-orb-ring"></div>
          <div class="voice-orb" id="voiceOrb">
            <span class="bar"></span>
            <span class="bar"></span>
            <span class="bar"></span>
            <span class="bar"></span>
          </div>
        </div>
        <div class="voice-overlay-label" id="voiceOverlayLabel">Listening…</div>
        <button type="button" class="voice-stop-btn" id="liveStop" title="Stop live voice" aria-label="Stop live voice">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
            <path d="M6 6l12 12M18 6L6 18"/>
          </svg>
        </button>
      </div>

      <div class="composer-wrap">
        <div class="composer">
          <textarea
            class="text-input"
            id="textInput"
            rows="1"
            placeholder="Type your message..."
          ></textarea>
          <div class="meeting-banner" id="meetingBanner">
            <span class="meeting-dot"></span>
            <span id="meetingBannerText">Recording meeting notes...</span>
          </div>
          <div class="composer-row">
            <div class="hint" id="hint">Type and press Send, or tap the voice button for live talk.</div>
            <button type="button" class="secondary meeting-active" id="meetingStart">Meeting</button>
            <button type="button" class="secondary" id="meetingEnd" disabled>End Meeting</button>
            <button type="button" class="secondary" id="sendText">Send</button>
            <button type="button" class="secondary" id="start">Start</button>
            <button type="button" id="stop" disabled>Stop</button>
            <button type="button" class="live-voice-btn" id="liveStart" title="Live voice" aria-label="Start live voice">
              <span class="wave" aria-hidden="true">
                <span></span><span></span><span></span><span></span>
              </span>
            </button>
          </div>
          <div class="now-playing" id="nowPlaying"></div>
        </div>
      </div>
    </div>

    <aside class="logs-panel" id="logsPanel">
      <div class="logs-header">
        <h2>Pipeline Logs</h2>
        <button class="secondary" id="clearLogs">Clear</button>
      </div>
      <div class="logs-body" id="logsBody">
        <div class="log-empty" id="logsEmpty">
          Open logs and send a query to watch each pipeline step appear here.
        </div>
        <div class="logs-list" id="logsList"></div>
      </div>
    </aside>
  </div>

  <div class="modal-backdrop" id="profileModal">
    <div class="modal">
      <h3>Personalisation</h3>
      <div class="field">
        <label for="profileName">Name</label>
        <input id="profileName" type="text" placeholder="Your name">
      </div>
      <div class="field">
        <label for="profileAge">Age</label>
        <input id="profileAge" type="text" placeholder="Your age">
      </div>
      <div class="field">
        <label for="profileDob">Date of birth</label>
        <input id="profileDob" type="date">
      </div>
      <div class="field">
        <label for="profileHeight">Height</label>
        <input id="profileHeight" type="text" placeholder="e.g. 5 ft 8 in">
      </div>
      <div class="field">
        <label for="profileWeight">Weight</label>
        <input id="profileWeight" type="text" placeholder="e.g. 70 kg">
      </div>
      <div class="modal-actions">
        <button class="secondary" id="closePersonalisation">Cancel</button>
        <button id="savePersonalisation">Save</button>
      </div>
    </div>
  </div>

<script src="/static/voice/live-voice.js?v=20260713-bargein-capture"></script>
<script>
const STREAM_TTS_MODE = "__STREAM_TTS_MODE__";
const USE_BROWSER_TTS = STREAM_TTS_MODE === "browser";
const MEETING_CHUNK_MS = Number("__AI_NOTES_CHUNK_INTERVAL__") * 1000;

let recorder;
let chunks = [];
let mediaStream = null;
let meetingRecorder = null;
let meetingStream = null;
let meetingSessionId = null;
let meetingActive = false;
let meetingUploadChain = Promise.resolve();
let activeHoldingBubble = null;
let activeAudio = null;
let abortController = null;
let isProcessing = false;
let activeChatId = null;
let logsPinnedToBottom = true;
let liveVoiceSession = null;
let liveVoiceActive = false;
let liveVoiceBusy = false;
let liveVoiceLevel = 0;
let liveAssistantText = "";
let liveBargeInCooldownUntil = 0;
let liveLastTtsEndedAt = 0;
let speechKeepaliveTimer = null;
let browserSpeechQueue = [];
let browserSpeechSpeaking = false;
let ttsInProgress = false;
let ttsJobQueue = [];
let ttsPrefetch = new Map();
let ttsAudioQueue = [];
let ttsNextSentenceIndex = 0;
let ttsAudioDrainRunning = false;
let ttsDrainRunning = false;
let streamAssistantBubble = null;
let streamBubbleIsHolding = false;
let spotifyQueue = [];
let spotifyIndex = 0;
let spotifyAudio = null;
let spotifyNowPlaying = null;
let spotifyPlayer = null;
let spotifyDeviceId = null;
let spotifySdkReady = false;
let spotifyInitPromise = null;
let spotifyIsPlaying = false;

const PROFILE_STORAGE_KEY = "luvio-profile";
const USER_ID_STORAGE_KEY = "luvio-user-id";

function getUserId() {
  let userId = localStorage.getItem(USER_ID_STORAGE_KEY);

  if (!userId) {
    userId = crypto.randomUUID();
    localStorage.setItem(USER_ID_STORAGE_KEY, userId);
  }

  return userId;
}

const app = document.getElementById("app");
const shell = document.getElementById("shell");
const start = document.getElementById("start");
const stop = document.getElementById("stop");
const liveStart = document.getElementById("liveStart");
const liveStop = document.getElementById("liveStop");
const voiceOverlay = document.getElementById("voiceOverlay");
const voiceOrb = document.getElementById("voiceOrb");
const voiceOverlayLabel = document.getElementById("voiceOverlayLabel");
const meetingStart = document.getElementById("meetingStart");
const meetingEnd = document.getElementById("meetingEnd");
const meetingBanner = document.getElementById("meetingBanner");
const meetingBannerText = document.getElementById("meetingBannerText");
const sendText = document.getElementById("sendText");
const textInput = document.getElementById("textInput");
const chatWrap = document.getElementById("chatWrap");
const chat = document.getElementById("chat");
const empty = document.getElementById("empty");
const status = document.getElementById("status");
const hint = document.getElementById("hint");
const logsToggle = document.getElementById("logsToggle");
const logsBody = document.getElementById("logsBody");
const logsList = document.getElementById("logsList");
const logsEmpty = document.getElementById("logsEmpty");
const clearLogs = document.getElementById("clearLogs");
const chatsList = document.getElementById("chatsList");
const newChat = document.getElementById("newChat");
const profileButton = document.getElementById("profileButton");
const profileMenu = document.getElementById("profileMenu");
const openPersonalisation = document.getElementById("openPersonalisation");
const profileModal = document.getElementById("profileModal");
const nowPlaying = document.getElementById("nowPlaying");
const closePersonalisation = document.getElementById("closePersonalisation");
const savePersonalisation = document.getElementById("savePersonalisation");
const profileName = document.getElementById("profileName");
const profileAge = document.getElementById("profileAge");
const profileDob = document.getElementById("profileDob");
const profileHeight = document.getElementById("profileHeight");
const profileWeight = document.getElementById("profileWeight");

logsBody.addEventListener("scroll", () => {
  const distanceFromBottom = logsBody.scrollHeight - logsBody.scrollTop - logsBody.clientHeight;
  logsPinnedToBottom = distanceFromBottom < 40;
});

function scrollChatToBottom() {
  chatWrap.scrollTop = chatWrap.scrollHeight;
}

function scrollLogsToBottom(force = false) {
  if (force || logsPinnedToBottom) {
    logsBody.scrollTop = logsBody.scrollHeight;
  }
}

function stopActiveAudio() {
  stopBrowserSpeech();

  if (activeAudio) {
    activeAudio.pause();
    activeAudio.currentTime = 0;
    activeAudio.src = "";
    activeAudio = null;
  }
}

let speechBufferText = "";
let activeSpeechLang = "en-IN";
let cachedSpeechVoices = [];

const INDIAN_LANGUAGE_SCRIPTS = [
  { pattern: /[\u0900-\u097F]/, lang: "hi-IN" },
  { pattern: /[\u0980-\u09FF]/, lang: "bn-IN" },
  { pattern: /[\u0A80-\u0AFF]/, lang: "gu-IN" },
  { pattern: /[\u0A00-\u0A7F]/, lang: "pa-IN" },
  { pattern: /[\u0B80-\u0BFF]/, lang: "ta-IN" },
  { pattern: /[\u0C00-\u0C7F]/, lang: "te-IN" },
  { pattern: /[\u0C80-\u0CFF]/, lang: "kn-IN" },
  { pattern: /[\u0D00-\u0D7F]/, lang: "ml-IN" },
  { pattern: /[\u0B00-\u0B7F]/, lang: "or-IN" },
  { pattern: /[\u0600-\u06FF]/, lang: "ur-IN" }
];

function normalizeLangCode(code) {
  return (code || "en-IN").replace("_", "-").toLowerCase();
}

function detectSpeechLang(...texts) {
  for (const text of texts) {
    if (!text) {
      continue;
    }

    for (const item of INDIAN_LANGUAGE_SCRIPTS) {
      if (item.pattern.test(text)) {
        return item.lang;
      }
    }
  }

  return activeSpeechLang || "en-IN";
}

function cacheSpeechVoices() {
  if (!window.speechSynthesis) {
    return;
  }

  cachedSpeechVoices = window.speechSynthesis.getVoices() || [];
}

function pickIndianVoice(langCode) {
  cacheSpeechVoices();

  const voices = cachedSpeechVoices;
  if (!voices.length) {
    return null;
  }

  const target = normalizeLangCode(langCode);
  const base = target.split("-")[0];

  const exact = voices.find(voice => normalizeLangCode(voice.lang) === target);
  if (exact) {
    return exact;
  }

  const regional = voices.filter(voice => {
    const lang = normalizeLangCode(voice.lang);
    return lang.startsWith(`${base}-in`);
  });

  if (regional.length) {
    return regional.find(voice => voice.localService) || regional[0];
  }

  const anyIndian = voices.filter(voice => normalizeLangCode(voice.lang).endsWith("-in"));
  if (anyIndian.length) {
    if (base === "en") {
      const englishIndia = anyIndian.find(voice => normalizeLangCode(voice.lang).startsWith("en-"));
      if (englishIndia) {
        return englishIndia;
      }
    }

    return anyIndian.find(voice => voice.localService) || anyIndian[0];
  }

  return null;
}

function setSpeechContext(transcript, langCode) {
  if (langCode) {
    activeSpeechLang = langCode;
    return;
  }

  activeSpeechLang = detectSpeechLang(transcript);
}

function resetSpeechBuffer() {
  speechBufferText = "";
}

function stopBrowserSpeech() {
  resetSpeechBuffer();
  browserSpeechQueue = [];
  browserSpeechSpeaking = false;
  stopSpeechKeepalive();

  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }

  syncLiveVoiceTtsSuppression();
}

function startSpeechKeepalive() {
  stopSpeechKeepalive();
  if (!window.speechSynthesis) {
    return;
  }

  speechKeepaliveTimer = setInterval(() => {
    if (window.speechSynthesis.speaking) {
      window.speechSynthesis.resume();
    }
  }, 800);
}

function stopSpeechKeepalive() {
  if (speechKeepaliveTimer) {
    clearInterval(speechKeepaliveTimer);
    speechKeepaliveTimer = null;
  }
}

function drainBrowserSpeechQueue() {
  if (!USE_BROWSER_TTS || !window.speechSynthesis || browserSpeechSpeaking) {
    return;
  }

  const next = browserSpeechQueue.shift();
  if (!next) {
    browserSpeechSpeaking = false;
    stopSpeechKeepalive();
    syncLiveVoiceTtsSuppression();
    updateTtsIdleStatus();
    return;
  }

  cacheSpeechVoices();
  const langCode = detectSpeechLang(next, "", activeSpeechLang);
  activeSpeechLang = langCode;
  const voice = pickIndianVoice(langCode);

  ttsInProgress = true;
  browserSpeechSpeaking = true;
  status.innerText = liveVoiceActive ? "Speaking" : "Speaking";
  if (liveVoiceActive) {
    setLiveVoiceUiState("speaking", "Speaking…");
    hint.innerText = "Replying… speak anytime to interrupt.";
  } else {
    hint.innerText = "Playing voice response...";
  }

  const utterance = new SpeechSynthesisUtterance(next);
  utterance.lang = langCode;
  if (voice) {
    utterance.voice = voice;
  }
  utterance.rate = 1.05;
  utterance.onstart = () => {
    syncLiveVoiceTtsSuppression(true);
    startSpeechKeepalive();
    if (liveVoiceActive && liveVoiceSession) {
      liveVoiceSession.setCanBargeIn(true);
      liveVoiceSession.setBargeInGraceMs(400);
    }
  };
  utterance.onend = () => {
    browserSpeechSpeaking = false;
    // Keep echo suppression up across sentence gaps in the queue.
    if (browserSpeechQueue.length || speechBufferText.trim()) {
      ttsInProgress = true;
      syncLiveVoiceTtsSuppression(true);
    }
    drainBrowserSpeechQueue();
  };
  utterance.onerror = () => {
    browserSpeechSpeaking = false;
    if (browserSpeechQueue.length || speechBufferText.trim()) {
      ttsInProgress = true;
      syncLiveVoiceTtsSuppression(true);
    }
    drainBrowserSpeechQueue();
  };

  try {
    window.speechSynthesis.resume();
  } catch (_) {
    /* ignore */
  }
  window.speechSynthesis.speak(utterance);
}

function speakBrowserChunk(text) {
  if (!USE_BROWSER_TTS || !window.speechSynthesis) {
    return;
  }

  const cleaned = text.trim();
  if (!cleaned) {
    return;
  }

  browserSpeechQueue.push(cleaned);
  drainBrowserSpeechQueue();
}

function extractSpeechChunks() {
  const chunks = [];
  const minChars = 10;
  const maxChars = 72;
  const sentenceEnd = /(?<=[.!?।\\n])\\s+/;

  while (speechBufferText) {
    const parts = speechBufferText.split(sentenceEnd);

    if (parts.length > 1 && parts[0].trim()) {
      chunks.push(parts[0].trim());
      speechBufferText = parts.slice(1).join(" ");
      continue;
    }

    const stripped = speechBufferText.trimStart();
    if (!stripped) {
      speechBufferText = "";
      break;
    }

    if (stripped.length >= maxChars) {
      let splitAt = stripped.lastIndexOf(" ", maxChars);
      if (splitAt < minChars) {
        splitAt = maxChars;
      }
      chunks.push(stripped.slice(0, splitAt).trim());
      speechBufferText = stripped.slice(splitAt).trimStart();
      continue;
    }

    let boundary = null;
    for (const marker of [".", "?", "!", "।", "\\n", ",", ";", ":"]) {
      const idx = stripped.indexOf(marker);
      if (idx !== -1) {
        const end = idx + 1;
        if (boundary === null || end < boundary) {
          boundary = end;
        }
      }
    }

    if (boundary !== null && boundary >= minChars) {
      chunks.push(stripped.slice(0, boundary).trim());
      speechBufferText = stripped.slice(boundary).trimStart();
      continue;
    }

    if (stripped.length >= minChars) {
      const spaceAt = stripped.indexOf(" ", minChars);
      if (spaceAt !== -1) {
        chunks.push(stripped.slice(0, spaceAt).trim());
        speechBufferText = stripped.slice(spaceAt).trimStart();
        continue;
      }
    }

    break;
  }

  return chunks;
}

function pushSpeechToken(text) {
  if (!USE_BROWSER_TTS || !text) {
    return;
  }

  speechBufferText += text;

  for (const chunk of extractSpeechChunks()) {
    speakBrowserChunk(chunk);
  }
}

function flushSpeechBuffer() {
  if (!USE_BROWSER_TTS) {
    return;
  }

  const remainder = speechBufferText.trim();
  resetSpeechBuffer();

  if (remainder) {
    speakBrowserChunk(remainder);
  }
}

function stopSpotifyAudio() {
  if (spotifyAudio) {
    spotifyAudio.pause();
    spotifyAudio.currentTime = 0;
    spotifyAudio.src = "";
    spotifyAudio = null;
  }
}

async function pauseSpotifyPlayback() {
  if (spotifyAudio) {
    spotifyAudio.pause();
  }

  if (spotifyPlayer) {
    await spotifyPlayer.pause();
  }

  spotifyIsPlaying = false;

  if (spotifyNowPlaying) {
    renderNowPlayingPanel(spotifyNowPlaying, { playing: false });
  }
}

async function stopSpotifyPlayback() {
  stopSpotifyAudio();

  if (spotifyPlayer) {
    await spotifyPlayer.pause();
  }

  spotifyIsPlaying = false;

  if (spotifyNowPlaying) {
    renderNowPlayingPanel(spotifyNowPlaying, { playing: false });
  }
}

async function resumeSpotifyPlayback() {
  if (spotifyAudio) {
    await spotifyAudio.play().catch(() => {});
    spotifyIsPlaying = true;
    renderNowPlayingPanel(spotifyNowPlaying, { playing: true });
    return;
  }

  if (spotifyPlayer) {
    await spotifyPlayer.resume();
    spotifyIsPlaying = true;
    renderNowPlayingPanel(spotifyNowPlaying, { playing: true });
    return;
  }

  if (spotifyQueue.length) {
    await playSpotifyTrackAt(spotifyIndex);
  }
}

async function toggleSpotifyPlayback() {
  if (spotifyIsPlaying) {
    await pauseSpotifyPlayback();
    return;
  }

  await resumeSpotifyPlayback();
}

function clearNowPlaying() {
  spotifyNowPlaying = null;
  spotifyIsPlaying = false;
  nowPlaying.classList.remove("active");
  nowPlaying.innerHTML = "";
}

function trackFromSdkState(state) {
  const current = state?.track_window?.current_track;
  if (!current) {
    return null;
  }

  const artists = (current.artists || [])
    .map(artist => artist.name)
    .filter(Boolean)
    .join(", ");

  return {
    track_id: current.id || "",
    uri: current.uri || "",
    name: current.name || "Unknown track",
    artists,
    label: artists ? `${current.name} by ${artists}` : current.name,
    image_url: current.album?.images?.[0]?.url || "",
    url: current.external_urls?.spotify || "",
  };
}

function renderNowPlayingPanel(track, options = {}) {
  if (!track) {
    clearNowPlaying();
    return;
  }

  const playing = options.playing !== false;
  spotifyIsPlaying = playing;
  const title = track.name || track.label || "Unknown track";
  const artist = track.artists || "";
  const artMarkup = track.image_url
    ? `<img class="now-playing-art" src="${track.image_url}" alt="">`
    : `<div class="now-playing-art"></div>`;

  nowPlaying.innerHTML = `
    <div class="now-playing-card">
      ${artMarkup}
      <div class="now-playing-meta">
        <div class="now-playing-title">${title}</div>
        ${artist ? `<div class="now-playing-artist">${artist}</div>` : ""}
        <div class="now-playing-status ${playing ? "" : "paused"}">
          <span class="now-playing-dot"></span>
          ${playing ? "Playing now" : "Paused"}
        </div>
      </div>
      <button
        type="button"
        class="now-playing-toggle secondary"
        data-spotify-toggle
        aria-label="${playing ? "Pause" : "Play"}"
      >${playing ? "Pause" : "Play"}</button>
    </div>
  `;
  nowPlaying.classList.add("active");
  spotifyNowPlaying = track;
}

function updateNowPlaying(track) {
  renderNowPlayingPanel(track, { playing: true });
}

function showSpotifyEmbed(track) {
  renderNowPlayingPanel(track, { playing: true });
}

function attachSpotifyPlayerListeners() {
  if (!spotifyPlayer || spotifyPlayer._luvioListenersAttached) {
    return;
  }

  spotifyPlayer._luvioListenersAttached = true;

  spotifyPlayer.addListener("player_state_changed", state => {
    if (!state) {
      spotifyIsPlaying = false;
      renderNowPlayingPanel(spotifyNowPlaying, { playing: false });
      return;
    }

    const track = trackFromSdkState(state) || spotifyNowPlaying;
    if (track) {
      spotifyIsPlaying = !state.paused;
      renderNowPlayingPanel(track, { playing: !state.paused });
    }
  });
}

function loadSpotifySdk() {
  if (window.Spotify) {
    return Promise.resolve();
  }

  return new Promise(resolve => {
    const script = document.createElement("script");
    script.src = "https://sdk.scdn.co/spotify-player.js";
    script.async = true;
    window.onSpotifyWebPlaybackSDKReady = () => resolve();
    document.body.appendChild(script);
  });
}

async function ensureSpotifyPlayer() {
  if (spotifySdkReady && spotifyDeviceId) {
    return true;
  }

  if (spotifyInitPromise) {
    return spotifyInitPromise;
  }

  spotifyInitPromise = (async () => {
    try {
      const config = await fetch("/api/spotify/config").then(response => response.json());

      if (!config.client_id || !config.connected || !config.has_streaming_scope) {
        return false;
      }

      await loadSpotifySdk();

      if (spotifyPlayer && spotifySdkReady) {
        attachSpotifyPlayerListeners();
        return true;
      }

      const ready = await new Promise(resolve => {
        let settled = false;

        const finish = value => {
          if (settled) return;
          settled = true;
          resolve(value);
        };

        window.setTimeout(() => finish(false), 8000);

        spotifyPlayer = new Spotify.Player({
          name: "Luvio Playground",
          getOAuthToken: callback => {
            fetch("/api/spotify/token")
              .then(response => {
                if (!response.ok) {
                  throw new Error("Spotify token unavailable");
                }
                return response.json();
              })
              .then(data => callback(data.access_token))
              .catch(() => callback(""));
          },
          volume: 1.0
        });

        spotifyPlayer.addListener("ready", ({ device_id }) => {
          spotifyDeviceId = device_id;
          spotifySdkReady = true;
          attachSpotifyPlayerListeners();
          finish(true);
        });

        spotifyPlayer.addListener("not_ready", () => {
          spotifySdkReady = false;
        });

        spotifyPlayer.addListener("initialization_error", () => finish(false));
        spotifyPlayer.addListener("authentication_error", () => finish(false));
        spotifyPlayer.addListener("account_error", () => finish(false));

        spotifyPlayer.connect();
      });

      return ready;
    } catch {
      return false;
    } finally {
      spotifyInitPromise = null;
    }
  })();

  return spotifyInitPromise;
}

async function playSpotifyTrackAt(index) {
  if (!spotifyQueue.length || index < 0 || index >= spotifyQueue.length) {
    return false;
  }

  const track = spotifyQueue[index];
  spotifyIndex = index;
  stopSpotifyAudio();
  updateNowPlaying(track);
  showSpotifyEmbed(track);
  status.innerText = "Playing music";
  hint.innerText = `Loaded ${track.label} in the playground player.`;

  if (track.preview_url) {
    spotifyAudio = new Audio(track.preview_url);
    spotifyAudio.onended = () => {
      if (spotifyIndex + 1 < spotifyQueue.length) {
        playSpotifyTrackAt(spotifyIndex + 1);
      }
    };
    hint.innerText = `Playing ${track.label} in the playground.`;
    spotifyIsPlaying = true;
    await spotifyAudio.play().catch(() => {});
    return true;
  }

  const config = await fetch("/api/spotify/config").then(response => response.json());

  if (config.connected && config.has_streaming_scope) {
    sessionStorage.removeItem("spotify_auth_pending");
  } else if (sessionStorage.getItem("spotify_auth_pending") !== "1") {
    sessionStorage.setItem("spotify_auth_pending", "1");
    redirectToSpotifyLogin({
      action: "play",
      tracks: spotifyQueue,
      index: spotifyIndex
    });
    return true;
  }

  if (spotifyPlayer && typeof spotifyPlayer.activateElement === "function") {
    spotifyPlayer.activateElement();
  }

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const playerReady = await ensureSpotifyPlayer();

    if (!playerReady || !track.uri || !spotifyDeviceId) {
      await new Promise(resolve => window.setTimeout(resolve, 400));
      continue;
    }

    const result = await fetch("/api/spotify/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        uri: track.uri,
        device_id: spotifyDeviceId
      })
    });

    if (result.ok) {
      hint.innerText = `Playing ${track.label} in the playground.`;
      spotifyIsPlaying = true;
      renderNowPlayingPanel(track, { playing: true });
      return true;
    }

    if (attempt === 2) {
      const error = await result.json().catch(() => ({}));
      hint.innerText = error.detail || `Loaded ${track.label}. Press play in the player below.`;
      return true;
    }

    await new Promise(resolve => window.setTimeout(resolve, 400));
  }

  hint.innerText = `Loaded ${track.label}. Press play in the player below (Spotify Premium required for auto-play).`;
  return true;
}

function redirectToSpotifyLogin(playback) {
  if (playback) {
    const pending = { ...playback };
    delete pending.needs_auth;
    sessionStorage.setItem("spotify_pending_playback", JSON.stringify(pending));
  }
  window.location.href = "/api/spotify/login";
}

async function resumePendingSpotifyPlayback() {
  const raw = sessionStorage.getItem("spotify_pending_playback");
  if (!raw) return;

  sessionStorage.removeItem("spotify_pending_playback");
  sessionStorage.removeItem("spotify_auth_pending");

  try {
    const playback = JSON.parse(raw);
    delete playback.needs_auth;
    await handleSpotifyPlayback(playback);
  } catch {
    // Ignore invalid pending playback payloads.
  }
}

async function handleSpotifyPlayback(playback) {
  if (!playback || !playback.action) {
    return;
  }

  if (playback.action === "connect") {
    const config = await fetch("/api/spotify/config").then(response => response.json());
    if (config.connected && config.has_streaming_scope) {
      sessionStorage.removeItem("spotify_auth_pending");
      return;
    }
    if (sessionStorage.getItem("spotify_auth_pending") !== "1") {
      redirectToSpotifyLogin(playback);
    }
    return;
  }

  if (playback.action === "play") {
    spotifyQueue = playback.tracks || [];
    await playSpotifyTrackAt(playback.index || 0);
    return;
  }

  if (playback.action === "pause") {
    await pauseSpotifyPlayback();
    status.innerText = "Paused";
    hint.innerText = "Playback paused in the playground.";
    return;
  }

  if (playback.action === "resume") {
    await resumeSpotifyPlayback();
    status.innerText = "Playing music";
    hint.innerText = "Playback resumed in the playground.";
    return;
  }

  if (playback.action === "next") {
    await playSpotifyTrackAt(spotifyIndex + 1);
    return;
  }

  if (playback.action === "previous") {
    await playSpotifyTrackAt(Math.max(0, spotifyIndex - 1));
    return;
  }

  if (playback.action === "now_playing") {
    if (spotifyNowPlaying) {
      hint.innerText = `Now playing: ${spotifyNowPlaying.label}`;
    } else {
      hint.innerText = "Nothing is playing in the playground right now.";
    }
  }
}

function emptyProfile() {
  return { name: "", age: "", dob: "", height: "", weight: "" };
}

function getStoredProfile() {
  try {
    const raw = localStorage.getItem(PROFILE_STORAGE_KEY);
    if (!raw) return emptyProfile();
    return { ...emptyProfile(), ...JSON.parse(raw) };
  } catch {
    return emptyProfile();
  }
}

function profileInitials(profile) {
  const name = (profile.name || "").trim() || "Guest";
  const parts = name.split(/\\s+/);

  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  return (name.slice(0, 2) || "G").toUpperCase();
}

function abortInFlightRequests() {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
}

function setComposerBusy(busy) {
  isProcessing = busy;
  sendText.disabled = busy || meetingActive || liveVoiceActive;
  textInput.disabled = busy || meetingActive || liveVoiceActive;
  start.disabled = busy || meetingActive || liveVoiceActive;
  stop.disabled = !recorder || recorder.state !== "recording" || meetingActive || liveVoiceActive;
  meetingStart.disabled = busy || meetingActive || liveVoiceActive;
  meetingEnd.disabled = !meetingActive || busy;
  liveStart.disabled = busy || meetingActive;
  liveStart.classList.toggle("active", liveVoiceActive);
}

function primeSpotifyAutoplay() {
  if (spotifyPlayer && typeof spotifyPlayer.activateElement === "function") {
    spotifyPlayer.activateElement();
    return;
  }

  ensureSpotifyPlayer().then(ready => {
    if (ready && spotifyPlayer && typeof spotifyPlayer.activateElement === "function") {
      spotifyPlayer.activateElement();
    }
  });
}

function clearChatMessages() {
  chat.querySelectorAll(".message").forEach(node => node.remove());
  empty.style.display = "grid";
}

function renderChatMessages(messages) {
  clearChatMessages();

  if (!messages || !messages.length) {
    return;
  }

  empty.style.display = "none";

  messages.forEach(message => {
    addMessage(message.role, message.text, false);
  });

  scrollChatToBottom();
}

function addMessage(role, text, shouldScroll = true) {
  empty.style.display = "none";

  const row = document.createElement("div");
  row.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerText = text;

  row.appendChild(bubble);
  chat.appendChild(row);

  if (shouldScroll) {
    scrollChatToBottom();
  }

  return bubble;
}

function appendLogs(logs) {
  if (!logs || !logs.length) return;

  logsEmpty.style.display = "none";

  logs.forEach(entry => {
    const row = document.createElement("div");
    row.className = "log-entry";

    const top = document.createElement("div");
    top.className = "log-top";

    const step = document.createElement("div");
    step.className = "log-step";
    step.innerText = entry.step;

    const badge = document.createElement("div");
    badge.className = `log-status ${entry.status}`;
    badge.innerText = entry.status;

    top.appendChild(step);
    top.appendChild(badge);

    const message = document.createElement("div");
    message.className = "log-message";
    message.innerText = entry.message;

    const time = document.createElement("div");
    time.className = "log-time";
    time.innerText = entry.timestamp;

    row.appendChild(top);
    row.appendChild(message);
    row.appendChild(time);

    if (entry.details && Object.keys(entry.details).length) {
      const details = document.createElement("pre");
      details.className = "log-details";
      details.innerText = JSON.stringify(entry.details, null, 2);
      row.appendChild(details);
    }

    logsList.appendChild(row);
  });

  scrollLogsToBottom();
}

function clearPipelineLogs() {
  logsList.innerHTML = "";
  logsEmpty.style.display = "block";
  logsBody.scrollTop = 0;
  logsPinnedToBottom = true;
}

async function playGeminiAudio(data) {
  if (!data.audio_base64) return;

  stopActiveAudio();

  return new Promise((resolve, reject) => {
    activeAudio = new Audio(
      `data:${data.mime_type || "audio/wav"};base64,${data.audio_base64}`
    );

    activeAudio.onplay = () => {
      ttsInProgress = true;
      syncLiveVoiceTtsSuppression(true);
      if (liveVoiceActive && liveVoiceSession) {
        liveVoiceSession.setCanBargeIn(true);
        liveVoiceSession.setBargeInGraceMs(400);
        setLiveVoiceUiState("speaking", "Speaking…");
        hint.innerText = "Replying… speak anytime to interrupt.";
      }
    };
    activeAudio.onended = () => {
      syncLiveVoiceTtsSuppression();
      resolve();
    };
    activeAudio.onerror = () => {
      syncLiveVoiceTtsSuppression();
      reject(new Error("Audio playback failed"));
    };
    activeAudio.play().catch(error => {
      syncLiveVoiceTtsSuppression();
      reject(error);
    });
  });
}

async function pollTtsJob(jobId) {
  const maxAttempts = 150;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const result = await fetch(`/api/tts/${jobId}`);

    if (result.status === 202) {
      await new Promise(resolve => window.setTimeout(resolve, attempt < 5 ? 40 : 80));
      continue;
    }

    if (!result.ok) {
      throw new Error(`TTS failed (${result.status})`);
    }

    return result.json();
  }

  throw new Error("Timed out waiting for voice response.");
}

function prefetchTtsJob(jobId) {
  if (!jobId || ttsPrefetch.has(jobId)) {
    return ttsPrefetch.get(jobId);
  }

  const promise = pollTtsJob(jobId).catch(error => {
    ttsPrefetch.delete(jobId);
    throw error;
  });

  ttsPrefetch.set(jobId, promise);
  return promise;
}

function resetTtsPlayback() {
  ttsJobQueue = [];
  ttsPrefetch.clear();
  ttsAudioQueue = [];
  ttsNextSentenceIndex = 0;
  ttsAudioDrainRunning = false;
  ttsDrainRunning = false;
  ttsInProgress = false;
  activeSpeechLang = "en-IN";
  stopBrowserSpeech();
  syncLiveVoiceTtsSuppression();
}

function isAssistantSpeaking() {
  if (ttsInProgress || browserSpeechSpeaking || browserSpeechQueue.length) {
    return true;
  }

  if (speechBufferText && speechBufferText.trim()) {
    return true;
  }

  if (ttsJobQueue.length || ttsAudioQueue.length || ttsPrefetch.size) {
    return true;
  }

  if (activeAudio && !activeAudio.paused) {
    return true;
  }

  if (
    USE_BROWSER_TTS &&
    window.speechSynthesis &&
    (window.speechSynthesis.speaking || window.speechSynthesis.pending)
  ) {
    return true;
  }

  return false;
}

function syncLiveVoiceTtsSuppression(forceActive) {
  if (!liveVoiceSession) {
    return;
  }

  const playing =
    typeof forceActive === "boolean"
      ? forceActive
      : isAssistantSpeaking();

  liveVoiceSession.setTtsPlaybackActive(playing);

  if (playing && liveVoiceActive) {
    if (liveVoiceSession.getState() !== "speaking") {
      liveVoiceSession.setState("speaking");
    }
  }
}

function normalizeEchoText(value) {
  return (value || "")
    .toLowerCase()
    .replace(/[^\\w\\s']/g, " ")
    .replace(/\\s+/g, " ")
    .trim();
}

function looksLikeEchoTranscript(transcript) {
  const text = normalizeEchoText(transcript);
  if (!text) {
    return true;
  }

  const words = text.split(" ").filter(Boolean);

  // Short fragments near assistant audio are almost always echo tails.
  const nearAssistantAudio =
    isAssistantSpeaking() ||
    Date.now() - liveLastTtsEndedAt < 8000 ||
    Date.now() < liveBargeInCooldownUntil + 8000;

  if (nearAssistantAudio && words.length <= 4) {
    return true;
  }

  if (words.length <= 2) {
    return true;
  }

  const opening = normalizeEchoText(liveAssistantText).slice(0, 280);
  if (!opening) {
    return nearAssistantAudio && words.length < 6;
  }

  if (opening.startsWith(text) || text.startsWith(opening.slice(0, Math.min(opening.length, 40)))) {
    return true;
  }

  if (opening.includes(text) || text.includes(opening.slice(0, Math.min(48, opening.length)))) {
    return true;
  }

  const significant = words.filter(word => word.length > 2);
  if (!significant.length) {
    return true;
  }

  const matched = significant.filter(word => opening.includes(word)).length;
  if (matched / significant.length >= 0.6) {
    return true;
  }

  // Ordered-word overlap against assistant opening.
  let cursor = 0;
  let orderedHits = 0;
  for (const word of significant) {
    const at = opening.indexOf(word, cursor);
    if (at === -1) {
      continue;
    }
    orderedHits += 1;
    cursor = at + word.length;
  }

  if (orderedHits >= Math.max(3, Math.ceil(significant.length * 0.55))) {
    return true;
  }

  return false;
}

function handleLiveBargeIn(meta = {}) {
  if (!liveVoiceActive) {
    return;
  }

  if (Date.now() < liveBargeInCooldownUntil) {
    return;
  }

  liveBargeInCooldownUntil = Date.now() + 900;

  appendLogs([{
    step: "voice.barge-in",
    status: "started",
    message: meta.duringTts
      ? "User interrupted TTS — capturing new question"
      : "User interrupted — cancelling in-flight reply",
    timestamp: new Date().toISOString(),
    details: meta
  }]);

  abortInFlightRequests();
  resetTtsPlayback();
  stopActiveAudio();
  liveVoiceBusy = false;
  setComposerBusy(false);

  if (liveVoiceSession) {
    liveVoiceSession.setCanBargeIn(false);
    // Keep the interrupt utterance; do not apply echo hangover discard.
    liveVoiceSession.setTtsPlaybackActive(false);
    liveVoiceSession.setState("user-speaking");
  }

  setLiveVoiceUiState("user-speaking", "Hearing you…");
  status.innerText = "Hearing you";
  status.className = "status recording";
  hint.innerText = "Interrupted — listening to your question.";
}

function defaultIdleHint() {
  if (liveVoiceActive) {
    return "Listening… speak naturally. Tap ✕ to exit.";
  }
  return "Type and press Send, or tap the voice button for live talk.";
}

function updateTtsIdleStatus() {
  if (isProcessing || isAssistantSpeaking()) {
    syncLiveVoiceTtsSuppression();
    return;
  }

  ttsInProgress = false;
  liveLastTtsEndedAt = Date.now();
  syncLiveVoiceTtsSuppression(false);

  if (liveVoiceActive) {
    if (liveVoiceSession) {
      const capturing =
        typeof liveVoiceSession.isBargeInCaptureActive === "function" &&
        liveVoiceSession.isBargeInCaptureActive();

      if (!capturing && typeof liveVoiceSession.ignoreUtterancesFor === "function") {
        liveVoiceSession.ignoreUtterancesFor(800);
      }
      if (liveVoiceSession.getState() !== "user-speaking" && !capturing) {
        liveVoiceSession.setState("listening");
        setLiveVoiceUiState("listening", "Listening…");
      }
      if (capturing) {
        status.innerText = "Hearing you";
        status.className = "status recording";
        hint.innerText = "Interrupted — listening to your question.";
        return;
      }
    }
    status.innerText = "Listening";
    status.className = "status recording";
    hint.innerText = defaultIdleHint();
    return;
  }

  if (spotifyNowPlaying) {
    status.innerText = "Playing music";
  } else {
    status.innerText = "Ready";
    hint.innerText = defaultIdleHint();
  }
}

async function drainTtsAudioQueue() {
  if (ttsAudioDrainRunning) {
    return;
  }

  ttsAudioDrainRunning = true;
  ttsInProgress = true;

  try {
    ttsAudioQueue.sort((left, right) => left.sentence_index - right.sentence_index);

    while (
      ttsAudioQueue.length &&
      ttsAudioQueue[0].sentence_index === ttsNextSentenceIndex
    ) {
      const event = ttsAudioQueue.shift();
      status.innerText = "Speaking";
      hint.innerText = "Playing voice response...";
      await playGeminiAudio(event);
      ttsNextSentenceIndex += 1;
    }
  } catch (error) {
    appendLogs([{
      step: "tts.error",
      status: "error",
      message: error.message || "Could not play voice response.",
      timestamp: new Date().toISOString(),
      details: {}
    }]);
  } finally {
    ttsAudioDrainRunning = false;
    updateTtsIdleStatus();

    if (ttsAudioQueue.length) {
      drainTtsAudioQueue();
    }
  }
}

function enqueueTtsAudio(event) {
  if (!event?.audio_base64) {
    return;
  }

  ttsAudioQueue.push(event);
  drainTtsAudioQueue();
}

async function drainTtsQueue() {
  if (ttsDrainRunning) {
    return;
  }

  ttsDrainRunning = true;
  ttsInProgress = true;

  try {
    while (ttsJobQueue.length) {
      const jobId = ttsJobQueue.shift();
      status.innerText = "Speaking";
      hint.innerText = "Playing voice response...";
      const audioData = await prefetchTtsJob(jobId);
      await playGeminiAudio(audioData);
      ttsPrefetch.delete(jobId);
    }
  } catch (error) {
    appendLogs([{
      step: "tts.error",
      status: "error",
      message: error.message || "Could not play voice response.",
      timestamp: new Date().toISOString(),
      details: {}
    }]);
  } finally {
    ttsDrainRunning = false;
    updateTtsIdleStatus();
  }
}

function enqueueTtsJob(jobId) {
  if (!jobId) return;
  ttsJobQueue.push(jobId);
  prefetchTtsJob(jobId);
  drainTtsQueue();
}

async function consumeNdjsonStream(response, onEvent) {
  if (!response.ok) {
    throw new Error(`Stream request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }

      await onEvent(JSON.parse(line));
    }
  }

  if (buffer.trim()) {
    await onEvent(JSON.parse(buffer));
  }
}

function setMeetingUiActive(active) {
  meetingActive = active;
  meetingBanner.classList.toggle("active", active);
  meetingStart.disabled = active || isProcessing || liveVoiceActive;
  meetingEnd.disabled = !active || isProcessing;
  start.disabled = active || liveVoiceActive;
  stop.disabled = active || liveVoiceActive || !recorder || recorder.state !== "recording";
  sendText.disabled = active || liveVoiceActive;
  textInput.disabled = active || liveVoiceActive;
  liveStart.disabled = active || isProcessing;

  if (active) {
    status.innerText = "Meeting";
    status.className = "status recording";
    hint.innerText = "Meeting notes are recording. Chunks upload automatically.";
    meetingBannerText.innerText = "Recording meeting notes...";
  }
}

async function uploadMeetingChunk(blob) {
  if (!blob || !blob.size || !meetingActive) {
    return;
  }

  const form = new FormData();
  form.append("audio", blob, `meeting-chunk-${Date.now()}.webm`);
  form.append("user_id", getUserId());

  meetingUploadChain = meetingUploadChain.then(async () => {
    const response = await fetch("/api/ai-notes/session/chunk", {
      method: "POST",
      body: form
    });

    if (!response.ok) {
      throw new Error(`Meeting chunk upload failed (${response.status})`);
    }

    const data = await response.json();
    meetingSessionId = data.session_id || meetingSessionId;
    meetingBannerText.innerText = `Recording meeting notes... ${data.chunk_count || 0} chunks saved`;
  });

  return meetingUploadChain;
}

async function startMeetingSession() {
  if (meetingActive || isProcessing || liveVoiceActive) {
    return;
  }

  stopActiveAudio();
  await stopSpotifyPlayback();
  abortInFlightRequests();

  const form = new FormData();
  form.append("user_id", getUserId());

  const response = await fetch("/api/ai-notes/session/start", {
    method: "POST",
    body: form
  });

  if (!response.ok) {
    throw new Error(`Could not start meeting session (${response.status})`);
  }

  const data = await response.json();
  meetingSessionId = data.session_id;
  meetingUploadChain = Promise.resolve();

  meetingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  meetingRecorder = new MediaRecorder(meetingStream, { mimeType: "audio/webm" });

  meetingRecorder.ondataavailable = event => {
    if (event.data.size > 0) {
      uploadMeetingChunk(event.data).catch(error => {
        appendLogs([{
          step: "ai-notes.session.chunk",
          status: "error",
          message: error.message || "Failed to upload meeting chunk.",
          timestamp: new Date().toISOString(),
          details: {}
        }]);
      });
    }
  };

  meetingRecorder.start(MEETING_CHUNK_MS);
  setMeetingUiActive(true);

  appendLogs([{
    step: "ai-notes.session.start",
    status: "completed",
    message: data.message || "Meeting recording started.",
    timestamp: new Date().toISOString(),
    details: { session_id: meetingSessionId }
  }]);

  if (data.tts?.audio_base64) {
    await playGeminiAudio(data.tts);
  } else if (data.message) {
    addMessage("assistant", data.message);
  }
}

async function endMeetingSession() {
  if (!meetingActive || isProcessing) {
    return;
  }

  setComposerBusy(true);
  meetingEnd.disabled = true;
  status.innerText = "Processing";
  hint.innerText = "Saving meeting notes...";

  if (meetingRecorder && meetingRecorder.state === "recording") {
    await new Promise(resolve => {
      meetingRecorder.onstop = resolve;
      meetingRecorder.stop();
    });
  }

  if (meetingStream) {
    meetingStream.getTracks().forEach(track => track.stop());
    meetingStream = null;
  }

  await meetingUploadChain;

  const form = new FormData();
  form.append("user_id", getUserId());

  streamAssistantBubble = null;
  streamBubbleIsHolding = false;
  resetTtsPlayback();

  try {
    const response = await fetch("/api/ai-notes/session/end", {
      method: "POST",
      body: form
    });

    let finalResponse = "";

    await consumeNdjsonStream(response, async event => {
      if (event.type === "status") {
        hint.innerText = event.message || "Processing meeting notes...";
        appendLogs([{
          step: "ai-notes.session.end",
          status: "started",
          message: event.message || "Processing meeting notes",
          timestamp: new Date().toISOString(),
          details: { session_id: event.session_id || meetingSessionId }
        }]);
        return;
      }

      if (event.type === "note_saved") {
        appendLogs([{
          step: "ai-notes.session.end",
          status: "completed",
          message: `Meeting note saved: ${event.title}`,
          timestamp: new Date().toISOString(),
          details: {
            note_id: event.note_id,
            pending_tasks: event.pending_tasks || []
          }
        }]);
        return;
      }

      if (event.type === "token") {
        if (!streamAssistantBubble) {
          streamAssistantBubble = addMessage("assistant", "");
        }
        streamAssistantBubble.innerText += event.text;
        finalResponse += event.text;
        scrollChatToBottom();
        if (USE_BROWSER_TTS) {
          pushSpeechToken(event.text);
        }
        return;
      }

      if (event.type === "error") {
        throw new Error(event.message || "Failed to save meeting notes.");
      }

      if (event.type === "done") {
        if (event.logs) {
          appendLogs(event.logs);
        }
        finalResponse = event.response || finalResponse;
      }
    });

    if (finalResponse && !streamAssistantBubble) {
      addMessage("assistant", finalResponse);
    }
  } finally {
    meetingRecorder = null;
    meetingSessionId = null;
    setMeetingUiActive(false);
    setComposerBusy(false);
    status.innerText = "Ready";
    status.className = "status";
    hint.innerText = defaultIdleHint();
  }
}

async function runStreamQuery(transcript, chatId, profile, signal, options = {}) {
  const isVoice = Boolean(options.voice);

  const response = isVoice
    ? await fetch("/api/voice-query/stream", {
        method: "POST",
        body: options.formData,
        signal
      })
    : await fetch("/api/query/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript,
          chat_id: chatId,
          profile,
          user_id: getUserId()
        }),
        signal
      });

  let finalData = null;
  streamAssistantBubble = null;
  streamBubbleIsHolding = false;
  resetTtsPlayback();

  await consumeNdjsonStream(response, async event => {
    if (event.type === "transcript") {
      if (event.text) {
        setSpeechContext(event.text, event.speech_lang);
      }
      if (options.onTranscript) {
        options.onTranscript(event.text);
      }
      return;
    }

    if (event.type === "intent") {
      if (event.speech_lang) {
        setSpeechContext("", event.speech_lang);
      }
      appendLogs([{
        step: "intent.classify",
        status: "completed",
        message: `Intent classified as ${event.intent}`,
        timestamp: new Date().toISOString(),
        details: {
          intent: event.intent,
          needs_holding: event.needs_holding
        }
      }]);

      if (event.needs_holding) {
        status.innerText = "Searching";
        hint.innerText = "Looking up the latest information...";
        if (liveVoiceActive) {
          setLiveVoiceUiState("thinking", "Searching…");
          if (liveVoiceSession) {
            liveVoiceSession.setCanBargeIn(true);
          }
        }
        streamAssistantBubble = addMessage(
          "assistant",
          event.holding_response || "One moment, I'll check that for you."
        );
        streamBubbleIsHolding = true;
      } else {
        status.innerText = "Thinking";
        if (liveVoiceActive) {
          setLiveVoiceUiState("thinking", "Thinking…");
        }
        streamAssistantBubble = addMessage("assistant", "");
        streamBubbleIsHolding = false;
      }
      return;
    }

    if (event.type === "token") {
      if (!streamAssistantBubble) {
        streamAssistantBubble = addMessage("assistant", "");
      }

      if (streamBubbleIsHolding) {
        streamAssistantBubble.innerText = event.text;
        streamBubbleIsHolding = false;
      } else {
        streamAssistantBubble.innerText += event.text;
      }
      if (liveVoiceActive) {
        liveAssistantText = streamAssistantBubble.innerText;
      }
      scrollChatToBottom();
      if (USE_BROWSER_TTS) {
        pushSpeechToken(event.text);
      }
      return;
    }

    if (event.type === "tts_audio") {
      if (!USE_BROWSER_TTS) {
        enqueueTtsAudio(event);
      }
      return;
    }

    if (event.type === "tts") {
      enqueueTtsJob(event.job_id);
      return;
    }

    if (event.type === "spotify_playback") {
      handleSpotifyPlayback(event.playback);
      return;
    }

    if (event.type === "done") {
      finalData = event;

      if (streamAssistantBubble && !event.response) {
        if (event.spotify_playback?.action === "play") {
          streamAssistantBubble.closest(".message")?.remove();
        } else {
          streamAssistantBubble.innerText = "(No response returned)";
        }
      }

      if (event.logs) {
        appendLogs(event.logs);
      }
    }
  });

  if (!finalData) {
    throw new Error("Stream ended before completion.");
  }

  if (USE_BROWSER_TTS) {
    flushSpeechBuffer();
  }

  return finalData;
}

async function ensureActiveChat() {
  if (activeChatId) {
    return activeChatId;
  }

  const result = await fetch("/api/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "New chat" })
  });

  const chatData = await result.json();
  activeChatId = chatData.id;
  await loadChats();
  return activeChatId;
}

async function loadChats() {
  const result = await fetch("/api/chats");
  const chats = await result.json();

  chatsList.innerHTML = "";

  chats.forEach(item => {
    const row = document.createElement("div");
    row.className = "chat-item-row";

    const button = document.createElement("button");
    button.className = "chat-item";
    button.dataset.chatId = item.id;
    button.title = item.title;
    button.innerText = item.title || "New chat";

    if (item.id === activeChatId) {
      button.classList.add("active");
    }

    button.onclick = () => selectChat(item.id);

    const deleteButton = document.createElement("button");
    deleteButton.className = "chat-delete secondary";
    deleteButton.innerText = "×";
    deleteButton.title = "Delete chat";
    deleteButton.onclick = async event => {
      event.stopPropagation();
      await deleteChat(item.id);
    };

    row.appendChild(button);
    row.appendChild(deleteButton);
    chatsList.appendChild(row);
  });
}

async function deleteChat(chatId) {
  const confirmed = window.confirm("Delete this chat?");
  if (!confirmed) return;

  await fetch(`/api/chats/${chatId}`, { method: "DELETE" });

  if (activeChatId === chatId) {
    activeChatId = null;
    clearChatMessages();
  }

  await loadChats();

  if (!activeChatId) {
    const result = await fetch("/api/chats");
    const chats = await result.json();

    if (chats.length) {
      await selectChat(chats[0].id);
    } else {
      await createNewChat();
    }
  }
}

async function loadProfile() {
  const profile = getStoredProfile();

  profileButton.innerText = profileInitials(profile);
  profileName.value = profile.name || "";
  profileAge.value = profile.age || "";
  profileDob.value = profile.dob || "";
  profileHeight.value = profile.height || "";
  profileWeight.value = profile.weight || "";
}

function saveProfile() {
  const profile = {
    name: profileName.value.trim(),
    age: profileAge.value.trim(),
    dob: profileDob.value,
    height: profileHeight.value.trim(),
    weight: profileWeight.value.trim()
  };

  localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile));
  profileButton.innerText = profileInitials(profile);
  profileModal.classList.remove("open");
  profileMenu.classList.remove("open");
}

async function selectChat(chatId) {
  stopActiveAudio();
  abortInFlightRequests();
  activeChatId = chatId;

  const result = await fetch(`/api/chats/${chatId}`);
  const chatData = await result.json();

  renderChatMessages(chatData.messages || []);
  await loadChats();
}

async function createNewChat() {
  stopActiveAudio();
  abortInFlightRequests();

  const result = await fetch("/api/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "New chat" })
  });

  const chatData = await result.json();
  activeChatId = chatData.id;
  clearChatMessages();
  await loadChats();
}

async function fetchTtsAndPlay(text, transcript) {
  const result = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, transcript })
  });

  if (!result.ok) {
    throw new Error(`TTS failed (${result.status})`);
  }

  const audioData = await result.json();
  appendLogs(audioData.logs || []);
  status.innerText = "Speaking";
  hint.innerText = "Playing voice response...";
  await playGeminiAudio(audioData);
}

async function pollTtsJobAndPlay(jobId) {
  const maxAttempts = 150;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const result = await fetch(`/api/tts/${jobId}`);

    if (result.status === 202) {
      await new Promise(resolve => setTimeout(resolve, 200));
      continue;
    }

    if (!result.ok) {
      throw new Error(`TTS failed (${result.status})`);
    }

    const audioData = await result.json();
    status.innerText = "Speaking";
    hint.innerText = "Playing voice response...";
    await playGeminiAudio(audioData);
    return;
  }

  throw new Error("Timed out waiting for voice response.");
}

async function playResponseTts(data, transcript) {
  if (!data.response) return;

  ttsInProgress = true;
  status.innerText = "Preparing voice";
  hint.innerText = "Generating speech...";

  try {
    if (data.tts_id) {
      await pollTtsJobAndPlay(data.tts_id);
    } else {
      await fetchTtsAndPlay(data.response, transcript);
    }
  } catch (error) {
    appendLogs([{
      step: "tts.error",
      status: "error",
      message: error.message || "Could not play voice response.",
      timestamp: new Date().toISOString(),
      details: {}
    }]);
  } finally {
    ttsInProgress = false;
    status.innerText = "Ready";
    hint.innerText = defaultIdleHint();
  }
}

async function startHoldingResponse(transcript, profile, signal) {
  if (!activeHoldingBubble) return;

  try {
    const result = await fetch("/api/holding-response", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript, profile, user_id: getUserId() }),
      signal
    });

    if (!result.ok) return;

    const data = await result.json();
    appendLogs(data.logs || []);

    if (activeHoldingBubble && data.response) {
      activeHoldingBubble.innerText = data.response;
    }
  } catch (error) {
    if (error.name === "AbortError") {
      throw error;
    }
  }
}

async function runTextQueryWithHolding(transcript, chatId, profile, signal) {
  const classifyResult = await fetch("/api/classify-text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript, profile, user_id: getUserId() }),
    signal
  });

  if (!classifyResult.ok) {
    throw new Error("Could not classify the query.");
  }

  const classifyData = await classifyResult.json();
  appendLogs(classifyData.logs || []);

  if (classifyData.needs_holding) {
    status.innerText = "Searching";
    hint.innerText = "Looking up the latest information...";
    activeHoldingBubble = addMessage(
      "assistant",
      classifyData.holding_response || "One moment, I'll check that for you."
    );
    startHoldingResponse(transcript, profile, signal);
  }

  const queryResult = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      transcript,
      chat_id: chatId,
      intent: classifyData.intent,
      profile,
      user_id: getUserId()
    }),
    signal
  });

  if (!queryResult.ok) {
    throw new Error("Could not generate a response.");
  }

  return queryResult.json();
}

async function runVoiceQueryWithHolding(audioBlob, chatId, profile, signal) {
  const form = new FormData();
  form.append("audio", audioBlob, "query.webm");

  const transcribeResult = await fetch("/api/transcribe-audio", {
    method: "POST",
    body: form,
    signal
  });

  if (!transcribeResult.ok) {
    throw new Error("Could not transcribe the audio.");
  }

  const classifyData = await transcribeResult.json();
  appendLogs(classifyData.logs || []);

  const transcript = classifyData.transcript || "(No transcript returned)";
  addMessage("user", transcript);

  if (classifyData.needs_holding) {
    status.innerText = "Searching";
    hint.innerText = "Looking up the latest information...";
    activeHoldingBubble = addMessage(
      "assistant",
      classifyData.holding_response || "One moment, I'll check that for you."
    );
    startHoldingResponse(transcript, profile, signal);
  }

  const queryResult = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      transcript,
      chat_id: chatId,
      intent: classifyData.intent,
      profile,
      user_id: getUserId()
    }),
    signal
  });

  if (!queryResult.ok) {
    throw new Error("Could not generate a response.");
  }

  const data = await queryResult.json();
  data.transcript = transcript;
  return data;
}

function showAssistantResponse(data) {
  const isSpotifyPlay = data.spotify_playback?.action === "play";

  if (activeHoldingBubble) {
    if (data.response) {
      activeHoldingBubble.innerText = data.response;
    } else if (!isSpotifyPlay) {
      activeHoldingBubble.innerText = "(No response returned)";
    } else {
      activeHoldingBubble.closest(".message")?.remove();
    }
  } else if (data.response) {
    addMessage("assistant", data.response);
  }

  handleSpotifyPlayback(data.spotify_playback);
}

async function processQuery(transcript) {
  abortInFlightRequests();
  abortController = new AbortController();
  const signal = abortController.signal;

  stopActiveAudio();
  await pauseSpotifyPlayback();
  activeHoldingBubble = null;
  streamAssistantBubble = null;
  streamBubbleIsHolding = false;
  resetTtsPlayback();
  setSpeechContext(transcript);

  if (!app.classList.contains("logs-open")) {
    app.classList.add("logs-open");
    logsToggle.classList.add("active");
  }

  clearPipelineLogs();
  setComposerBusy(true);
  status.innerText = "Thinking";
  status.className = "status";
  hint.innerText = "Processing your query...";

  const profile = getStoredProfile();

  try {
    const chatId = await ensureActiveChat();
    addMessage("user", transcript);

    const data = await runStreamQuery(
      transcript,
      chatId,
      profile,
      signal
    );

    appendLogs([{
      step: "session.complete",
      status: "completed",
      message: "Playground query finished",
      timestamp: new Date().toISOString(),
      details: { intent: data.intent }
    }]);

    loadChats();
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }

    appendLogs([{
      step: "session.error",
      status: "error",
      message: error.message || "Something went wrong while processing the query.",
      timestamp: new Date().toISOString(),
      details: {}
    }]);

    if (streamAssistantBubble) {
      streamAssistantBubble.innerText = "Something went wrong while processing the query.";
    } else {
      addMessage("assistant", "Something went wrong while processing the query.");
    }
  } finally {
    activeHoldingBubble = null;
    streamAssistantBubble = null;
    streamBubbleIsHolding = false;
    setComposerBusy(false);
    start.disabled = false;
    stop.disabled = true;
    if (!ttsInProgress) {
      if (spotifyNowPlaying) {
        status.innerText = "Playing music";
      } else {
        status.innerText = "Ready";
        hint.innerText = defaultIdleHint();
      }
    }
    abortController = null;
  }
}

logsToggle.onclick = () => {
  app.classList.toggle("logs-open");
  logsToggle.classList.toggle("active");
};

clearLogs.onclick = clearPipelineLogs;
newChat.onclick = createNewChat;

profileButton.onclick = event => {
  event.stopPropagation();
  profileMenu.classList.toggle("open");
};

openPersonalisation.onclick = () => {
  profileMenu.classList.remove("open");
  profileModal.classList.add("open");
};

closePersonalisation.onclick = () => {
  profileModal.classList.remove("open");
};

savePersonalisation.onclick = saveProfile;

profileModal.onclick = event => {
  if (event.target === profileModal) {
    profileModal.classList.remove("open");
  }
};

document.addEventListener("click", () => {
  profileMenu.classList.remove("open");
});

nowPlaying.addEventListener("click", event => {
  if (!event.target.closest("[data-spotify-toggle]")) {
    return;
  }

  event.preventDefault();
  toggleSpotifyPlayback();
});

function setLiveVoiceUiState(state, label) {
  if (!voiceOverlay) {
    return;
  }

  voiceOverlay.dataset.state = state || "listening";
  if (label) {
    voiceOverlayLabel.innerText = label;
  }

  if (state === "user-speaking") {
    applyLiveVoiceLevel(Math.max(liveVoiceLevel, 0.08));
  } else if (state === "listening") {
    applyLiveVoiceLevel(0.02);
  }
}

function applyLiveVoiceLevel(rms) {
  liveVoiceLevel = rms;
  if (!voiceOrb) {
    return;
  }

  const intensity = Math.min(1, Math.max(0, (rms - 0.01) / 0.12));
  const heights = [
    14 + intensity * 18,
    28 + intensity * 28,
    22 + intensity * 24,
    14 + intensity * 18,
  ];
  const bars = voiceOrb.querySelectorAll(".bar");
  bars.forEach((bar, index) => {
    bar.style.height = `${heights[index] || 16}px`;
  });

  const scale = 1 + intensity * 0.08;
  voiceOrb.style.transform = `scale(${scale})`;
}

function handleLiveVoiceStateChange(state) {
  if (!liveVoiceActive) {
    return;
  }

  if (state === "listening") {
    setLiveVoiceUiState("listening", "Listening…");
    status.innerText = "Listening";
    status.className = "status recording";
    hint.innerText = defaultIdleHint();
    if (liveVoiceSession && isAssistantSpeaking()) {
      liveVoiceSession.setCanBargeIn(true);
    }
    return;
  }

  if (state === "user-speaking") {
    setLiveVoiceUiState("user-speaking", "Listening to you…");
    status.innerText = "Hearing you";
    status.className = "status recording";
    hint.innerText = "Speak naturally — pause when finished.";
    return;
  }

  if (state === "thinking") {
    setLiveVoiceUiState("thinking", "Thinking…");
    status.innerText = "Thinking";
    status.className = "status";
    hint.innerText = "Working on your request… speak to interrupt.";
    if (liveVoiceSession) {
      liveVoiceSession.setCanBargeIn(true);
    }
    return;
  }

  if (state === "speaking") {
    setLiveVoiceUiState("speaking", "Speaking…");
    status.innerText = "Speaking";
    status.className = "status";
    hint.innerText = "Replying… speak anytime to interrupt.";
    if (liveVoiceSession) {
      liveVoiceSession.setCanBargeIn(true);
    }
  }
}

function handleLiveVadMisfire() {
  if (!liveVoiceActive || !liveVoiceSession) {
    return;
  }

  if (isAssistantSpeaking()) {
    liveVoiceSession.setCanBargeIn(true);
  }
}

async function processLiveUtterance(blob, meta = {}) {
  if (!liveVoiceActive || !blob || !blob.size) {
    return;
  }

  if (liveVoiceBusy && !meta.fromBargeIn) {
    return;
  }

  liveVoiceBusy = true;
  liveAssistantText = "";

  abortInFlightRequests();
  abortController = new AbortController();
  const signal = abortController.signal;

  stopActiveAudio();
  await pauseSpotifyPlayback();
  resetTtsPlayback();
  activeHoldingBubble = null;
  streamAssistantBubble = null;
  streamBubbleIsHolding = false;

  if (!app.classList.contains("logs-open")) {
    app.classList.add("logs-open");
    logsToggle.classList.add("active");
  }

  setComposerBusy(true);
  if (liveVoiceSession) {
    liveVoiceSession.setState("thinking");
    liveVoiceSession.setCanBargeIn(true);
  }
  setLiveVoiceUiState("thinking", "Thinking…");
  status.innerText = "Thinking";
  status.className = "status";
  hint.innerText = "Transcribing and answering…";

  appendLogs([{
    step: "voice.utterance",
    status: "started",
    message: "Live voice utterance captured",
    timestamp: new Date().toISOString(),
    details: {
      durationMs: meta.durationMs || null,
      format: meta.format || blob.type || "audio/wav",
      vad: meta.vad || liveVoiceSession?.getCaptureMode() || "unknown"
    }
  }]);

  try {
    const chatId = await ensureActiveChat();
    const profile = getStoredProfile();
    const extension = (meta.format || blob.type || "").includes("webm") ? "webm" : "wav";

    const form = new FormData();
    form.append("audio", blob, `live-query.${extension}`);
    form.append("chat_id", chatId);
    form.append("user_id", getUserId());
    form.append("profile", JSON.stringify(profile));

    const data = await runStreamQuery(
      "",
      chatId,
      profile,
      signal,
      {
        voice: true,
        formData: form,
        onTranscript: text => {
          if (looksLikeEchoTranscript(text)) {
            appendLogs([{
              step: "voice.echo-filter",
              status: "completed",
              message: `Ignored likely TTS echo: "${text}"`,
              timestamp: new Date().toISOString(),
              details: {}
            }]);
            abortInFlightRequests();
            return;
          }

          addMessage("user", text);
          setSpeechContext(text);
          status.innerText = "Thinking";
          hint.innerText = "Generating response...";
        }
      }
    );

    if (signal.aborted) {
      return;
    }

    liveAssistantText = data.response || streamAssistantBubble?.innerText || "";

    appendLogs([{
      step: "session.complete",
      status: "completed",
      message: "Live voice turn finished",
      timestamp: new Date().toISOString(),
      details: { intent: data.intent }
    }]);

    loadChats();
  } catch (error) {
    if (error.name === "AbortError") {
      if (liveVoiceActive && liveVoiceSession) {
        liveVoiceSession.setState("listening");
        liveVoiceSession.setCanBargeIn(isAssistantSpeaking());
      }
      return;
    }

    appendLogs([{
      step: "session.error",
      status: "error",
      message: error.message || "Live voice turn failed.",
      timestamp: new Date().toISOString(),
      details: {}
    }]);

    if (streamAssistantBubble) {
      streamAssistantBubble.innerText = "Something went wrong while processing the audio.";
    } else if (liveVoiceActive) {
      addMessage("assistant", "Something went wrong while processing the audio.");
    }
  } finally {
    activeHoldingBubble = null;
    streamAssistantBubble = null;
    streamBubbleIsHolding = false;
    liveVoiceBusy = false;
    setComposerBusy(false);
    abortController = null;

    if (liveVoiceActive) {
      if (!isAssistantSpeaking() && liveVoiceSession) {
        liveVoiceSession.setState("listening");
        setLiveVoiceUiState("listening", "Listening…");
        status.innerText = "Listening";
        status.className = "status recording";
        hint.innerText = defaultIdleHint();
      } else if (isAssistantSpeaking() && liveVoiceSession) {
        liveVoiceSession.setState("speaking");
        liveVoiceSession.setCanBargeIn(true);
      }
    } else if (!ttsInProgress) {
      status.innerText = spotifyNowPlaying ? "Playing music" : "Ready";
      hint.innerText = defaultIdleHint();
    }
  }
}

async function startLiveVoice() {
  if (liveVoiceActive || meetingActive || typeof LiveVoiceSession !== "function") {
    if (typeof LiveVoiceSession !== "function") {
      throw new Error("Live voice script failed to load.");
    }
    return;
  }

  if (recorder && recorder.state === "recording") {
    throw new Error("Stop the push-to-talk recording before starting Live.");
  }

  stopActiveAudio();
  await stopSpotifyPlayback();
  abortInFlightRequests();
  resetTtsPlayback();

  liveVoiceSession = new LiveVoiceSession({
    processorUrl: "/static/voice/pcm-capture-processor.js",
    onStateChange: state => handleLiveVoiceStateChange(state),
    onLevel: rms => {
      if (liveVoiceActive) {
        applyLiveVoiceLevel(rms);
      }
    },
    onBargeIn: meta => handleLiveBargeIn(meta || {}),
    onVADMisfire: () => handleLiveVadMisfire(),
    onUtterance: (blob, meta) => {
      processLiveUtterance(blob, meta).catch(error => {
        appendLogs([{
          step: "voice.utterance",
          status: "error",
          message: error.message || "Could not process live utterance.",
          timestamp: new Date().toISOString(),
          details: {}
        }]);
      });
    },
    vad: {
      engine: "silero",
      positiveSpeechThreshold: 0.72,
      negativeSpeechThreshold: 0.42,
      minSpeechMs: 420,
      redemptionMs: 650,
      bargeInSpeechThreshold: 0.74,
      bargeInDuringTtsThreshold: 0.9,
      bargeInMinMsDuringTts: 450,
      bargeInGraceMs: 550,
      ttsEchoRmsMultiplier: 1.55,
      postTtsHangoverMs: 1000,
    }
  });

  await liveVoiceSession.start();
  liveVoiceActive = true;
  shell?.classList.add("live-active");
  voiceOverlay.classList.add("active");
  voiceOverlay.setAttribute("aria-hidden", "false");
  liveStart.classList.add("active");
  setComposerBusy(false);
  setLiveVoiceUiState("listening", "Listening…");
  status.innerText = "Listening";
  status.className = "status recording";
  hint.innerText = defaultIdleHint();

  appendLogs([{
    step: "voice.live.start",
    status: "completed",
    message: `Live voice started (${liveVoiceSession.getCaptureMode()})`,
    timestamp: new Date().toISOString(),
    details: {
      engine: liveVoiceSession.getCaptureMode(),
      noiseSuppression: true,
      echoCancellation: true
    }
  }]);
}

async function stopLiveVoice() {
  if (!liveVoiceActive && !liveVoiceSession) {
    return;
  }

  abortInFlightRequests();
  resetTtsPlayback();
  stopActiveAudio();

  const session = liveVoiceSession;
  liveVoiceSession = null;
  liveVoiceActive = false;
  liveVoiceBusy = false;
  liveAssistantText = "";

  if (session) {
    try {
      await session.stop();
    } catch (error) {
      console.warn("Could not stop live voice session", error);
    }
  }

  voiceOverlay.classList.remove("active");
  voiceOverlay.setAttribute("aria-hidden", "true");
  voiceOverlay.dataset.state = "idle";
  shell?.classList.remove("live-active");
  liveStart.classList.remove("active");
  setComposerBusy(false);
  status.innerText = "Ready";
  status.className = "status";
  hint.innerText = defaultIdleHint();

  appendLogs([{
    step: "voice.live.stop",
    status: "completed",
    message: "Live voice stopped",
    timestamp: new Date().toISOString(),
    details: {}
  }]);
}

sendText.onclick = async () => {
  const transcript = textInput.value.trim();
  if (!transcript || isProcessing || liveVoiceActive) return;
  textInput.value = "";
  primeSpotifyAutoplay();
  await processQuery(transcript);
};

textInput.addEventListener("keydown", async event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendText.click();
  }
});

start.onclick = async () => {
  if (meetingActive || liveVoiceActive) {
    return;
  }

  stopActiveAudio();
  await stopSpotifyPlayback();
  abortInFlightRequests();

  if (recorder && recorder.state === "recording") {
    return;
  }

  chunks = [];

  mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

  recorder = new MediaRecorder(mediaStream, {
    mimeType: "audio/webm"
  });

  recorder.ondataavailable = event => {
    if (event.data.size > 0) {
      chunks.push(event.data);
    }
  };

  recorder.start();

  start.disabled = true;
  stop.disabled = false;
  sendText.disabled = true;
  textInput.disabled = true;
  liveStart.disabled = true;
  status.innerText = "Recording";
  status.className = "status recording";
  hint.innerText = "Listening... Spotify paused while recording.";
};

stop.onclick = async () => {
  if (meetingActive || liveVoiceActive) {
    return;
  }

  if (!recorder || recorder.state !== "recording") {
    return;
  }

  primeSpotifyAutoplay();
  stop.disabled = true;
  status.innerText = "Thinking";
  status.className = "status";
  hint.innerText = "Sending audio to Luvio...";

  appendLogs([{
    step: "speech.record",
    status: "completed",
    message: "Browser finished recording audio from microphone",
    timestamp: new Date().toISOString(),
    details: { format: "audio/webm" }
  }]);

  recorder.stop();

  recorder.onstop = async () => {
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop());
      mediaStream = null;
    }

    try {
      const blob = new Blob(chunks, { type: "audio/webm" });

      appendLogs([{
        step: "speech.record",
        status: "completed",
        message: "Browser finished recording audio from microphone",
        timestamp: new Date().toISOString(),
        details: { format: "audio/webm" }
      }]);

      if (!app.classList.contains("logs-open")) {
        app.classList.add("logs-open");
        logsToggle.classList.add("active");
      }

      clearPipelineLogs();
      setComposerBusy(true);

      const chatId = await ensureActiveChat();
      const profile = getStoredProfile();

      abortController = new AbortController();
      const signal = abortController.signal;

      const form = new FormData();
      form.append("audio", blob, "query.webm");
      form.append("chat_id", chatId);
      form.append("user_id", getUserId());
      form.append("profile", JSON.stringify(profile));

      streamAssistantBubble = null;
      streamBubbleIsHolding = false;
      resetTtsPlayback();

      const data = await runStreamQuery(
        "",
        chatId,
        profile,
        signal,
        {
          voice: true,
          formData: form,
          onTranscript: text => {
            addMessage("user", text);
            status.innerText = "Thinking";
            hint.innerText = "Generating response...";
          }
        }
      );

      appendLogs([{
        step: "session.complete",
        status: "completed",
        message: "Playground query finished",
        timestamp: new Date().toISOString(),
        details: { intent: data.intent }
      }]);

      loadChats();
    } catch (error) {
      if (error.name !== "AbortError") {
        appendLogs([{
          step: "session.error",
          status: "error",
          message: error.message || "Something went wrong while processing the audio.",
          timestamp: new Date().toISOString(),
          details: {}
        }]);

        if (streamAssistantBubble) {
          streamAssistantBubble.innerText = "Something went wrong while processing the audio.";
        }
      }
    } finally {
      activeHoldingBubble = null;
      streamAssistantBubble = null;
      streamBubbleIsHolding = false;
      setComposerBusy(false);
      if (!ttsInProgress) {
        if (spotifyNowPlaying) {
          status.innerText = "Playing music";
        } else {
          status.innerText = "Ready";
          hint.innerText = defaultIdleHint();
        }
      }
      abortController = null;
    }
  };
};

meetingStart.onclick = async () => {
  try {
    if (liveVoiceActive) {
      await stopLiveVoice();
    }
    await startMeetingSession();
  } catch (error) {
    appendLogs([{
      step: "ai-notes.session.start",
      status: "error",
      message: error.message || "Could not start meeting session.",
      timestamp: new Date().toISOString(),
      details: {}
    }]);
    setMeetingUiActive(false);
  }
};

meetingEnd.onclick = async () => {
  try {
    await endMeetingSession();
  } catch (error) {
    appendLogs([{
      step: "ai-notes.session.end",
      status: "error",
      message: error.message || "Could not end meeting session.",
      timestamp: new Date().toISOString(),
      details: {}
    }]);
    setMeetingUiActive(false);
    setComposerBusy(false);
  }
};

liveStart.onclick = async () => {
  try {
    if (liveVoiceActive) {
      await stopLiveVoice();
      return;
    }
    await startLiveVoice();
  } catch (error) {
    await stopLiveVoice();
    appendLogs([{
      step: "voice.live.start",
      status: "error",
      message: error.message || "Could not start live voice.",
      timestamp: new Date().toISOString(),
      details: {}
    }]);
    status.innerText = "Ready";
    status.className = "status";
    hint.innerText = error.message || "Could not start live voice.";
  }
};

liveStop.onclick = async () => {
  await stopLiveVoice();
};

loadProfile();
if (window.speechSynthesis) {
  window.speechSynthesis.addEventListener("voiceschanged", cacheSpeechVoices);
  cacheSpeechVoices();
}
loadChats().then(async () => {
  const result = await fetch("/api/chats");
  const chats = await result.json();

  if (chats.length) {
    await selectChat(chats[0].id);
  } else {
    await createNewChat();
  }

  ensureSpotifyPlayer().finally(() => {
    resumePendingSpotifyPlayback();
  });
});
</script>
</body>
</html>
"""


@app.get("/api/chats")
def list_chats():
    return orchestrator.list_chats()


@app.post("/api/chats")
def create_chat(request: CreateChatRequest):
    return orchestrator.create_chat(request.title)


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    chat = orchestrator.get_chat(chat_id)

    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    return chat


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    deleted = orchestrator.delete_chat(chat_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Chat not found")

    return {"deleted": True}


@app.get("/api/spotify/status")
def spotify_status():
    return {
        "configured": spotify_client.is_configured(),
        "connected": spotify_client.is_connected(),
        "has_streaming_scope": spotify_client.has_streaming_scope(),
        "mode": "playground_player",
    }


@app.get("/api/spotify/config")
def spotify_config():
    return {
        "client_id": SPOTIFY_CLIENT_ID,
        "configured": spotify_client.is_configured(),
        "connected": spotify_client.is_connected(),
        "has_streaming_scope": spotify_client.has_streaming_scope(),
    }


@app.get("/api/spotify/token")
def spotify_token():
    token = spotify_client.get_access_token()

    if not token:
        raise HTTPException(status_code=401, detail="Spotify is not connected")

    return {"access_token": token}


@app.post("/api/spotify/play")
def spotify_play(request: SpotifyPlayRequest):
    try:
        spotify_client.play_uri(
            request.uri,
            request.device_id,
        )
    except SpotifyAuthRequired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SpotifyApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"playing": True}


@app.get("/api/spotify/login")
def spotify_login():
    if not spotify_client.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Spotify credentials are missing from .env",
        )

    return RedirectResponse(spotify_client.authorization_url())


@app.get("/api/spotify/callback", response_class=HTMLResponse)
def spotify_callback(
    code: str | None = None,
    error: str | None = None,
):
    if error:
        return HTMLResponse(
            f"<h1>Spotify connection failed</h1><p>{error}</p>",
            status_code=400,
        )

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    spotify_client.exchange_code(code)

    return HTMLResponse(
        """
        <html>
          <body style="font-family: sans-serif; padding: 40px;">
            <h1>Spotify connected</h1>
            <p>Returning to the Luvio playground...</p>
            <script>
              sessionStorage.removeItem("spotify_auth_pending");
              window.location.href = "/";
            </script>
          </body>
        </html>
        """
    )


@app.post("/api/spotify/disconnect")
def spotify_disconnect():
    spotify_client.disconnect()
    return {"connected": False}


@app.get("/api/memory/status")
def memory_status():
    return orchestrator.memory_status()


@app.post("/api/query/stream")
def query_stream(request: TranscriptRequest):
    return StreamingResponse(
        stream_ndjson_response(
            stream_query(
                orchestrator,
                request.transcript,
                chat_id=request.chat_id,
                profile=_profile_payload(request.profile),
                user_id=request.user_id,
            )
        ),
        media_type="application/x-ndjson",
    )


@app.post("/api/voice-query/stream")
async def voice_query_stream(
    audio: UploadFile = File(...),
    chat_id: str | None = Form(default=None),
    user_id: str | None = Form(default=None),
    profile: str | None = Form(default=None),
):
    audio_bytes = await audio.read()
    profile_payload = None

    if profile:
        try:
            profile_payload = json.loads(profile)
        except json.JSONDecodeError:
            profile_payload = None

    return StreamingResponse(
        stream_ndjson_response(
            stream_voice_query(
                orchestrator,
                audio_bytes,
                mime_type=audio.content_type or "audio/webm",
                chat_id=chat_id,
                user_id=user_id,
                profile=profile_payload,
            )
        ),
        media_type="application/x-ndjson",
    )


@app.post("/api/query")
def query(request: TranscriptRequest):
    with pipeline_session() as pipeline_logger:
        result = orchestrator.process_query(
            request.transcript,
            chat_id=request.chat_id,
            intent=request.intent,
            profile=_profile_payload(request.profile),
            user_id=request.user_id,
        )
        result["logs"] = pipeline_logger.to_list()
        return result


@app.post("/api/voice-query")
async def voice_query(
    audio: UploadFile = File(...),
    chat_id: str | None = Form(default=None),
    user_id: str | None = Form(default=None),
    profile: str | None = Form(default=None),
):
    audio_bytes = await audio.read()
    profile_payload = None

    if profile:
        try:
            profile_payload = json.loads(profile)
        except json.JSONDecodeError:
            profile_payload = None

    with pipeline_session() as pipeline_logger:
        result = orchestrator.process_voice_query(
            audio_bytes=audio_bytes,
            mime_type=audio.content_type or "audio/webm",
            chat_id=chat_id,
            user_id=user_id,
            profile=profile_payload,
        )
        result["logs"] = pipeline_logger.to_list()
        return result


@app.post("/api/tts")
def tts(request: TtsRequest):
    with pipeline_session() as pipeline_logger:
        audio = orchestrator.generate_tts(
            request.text,
            transcript=request.transcript,
        )
        return {
            **audio,
            "logs": pipeline_logger.to_list(),
        }


@app.get("/api/tts/{job_id}")
def get_tts(job_id: str):
    job = get_tts_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="TTS job not found")

    if job["status"] == "pending":
        return JSONResponse(
            status_code=202,
            content={"status": "pending"},
        )

    if job["status"] == "error":
        raise HTTPException(
            status_code=500,
            detail=job["error"] or "TTS generation failed",
        )

    return job["result"]


@app.post("/api/classify-text")
def classify_text(request: TranscriptRequest):
    with pipeline_session() as pipeline_logger:
        result = orchestrator.prepare_text_query(
            request.transcript
        )
        result["logs"] = pipeline_logger.to_list()
        return result


@app.post("/api/query-audio")
async def query_audio(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()

    with pipeline_session() as pipeline_logger:
        result = orchestrator.process_audio_bytes(
            audio_bytes=audio_bytes,
            mime_type=audio.content_type or "audio/webm",
        )
        result["logs"] = pipeline_logger.to_list()
        return result


@app.post("/api/transcribe-audio")
async def transcribe_audio(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()

    with pipeline_session() as pipeline_logger:
        result = orchestrator.transcribe_audio_bytes(
            audio_bytes=audio_bytes,
            mime_type=audio.content_type or "audio/webm",
        )
        result["logs"] = pipeline_logger.to_list()
        return result


@app.post("/api/holding-response")
def holding_response(request: TranscriptRequest):
    with pipeline_session() as pipeline_logger:
        response = orchestrator.build_holding_response(
            request.transcript
        )
        return {
            "response": response,
            "logs": pipeline_logger.to_list(),
        }


@app.post("/api/respond")
def respond(request: TranscriptRequest):
    with pipeline_session() as pipeline_logger:
        history = None

        if request.chat_id:
            history = orchestrator.chats.get_history(
                request.chat_id
            )

        result = orchestrator.process_transcript(
            request.transcript,
            history=history,
            intent=request.intent,
            chat_id=request.chat_id,
            profile=_profile_payload(request.profile),
            user_id=request.user_id,
        )
        result["logs"] = pipeline_logger.to_list()
        return result
