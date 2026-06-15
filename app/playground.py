from contextlib import contextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.config import SPOTIFY_CLIENT_ID
from app.conversation.tts_jobs import get_tts_job
from app.orchestrator.intelligence import IntelligenceOrchestrator
from app.tools.spotify_client import SpotifyClient, SpotifyApiError, SpotifyAuthRequired
from app.utils.pipeline_log import (
    PipelineLogger,
    reset_pipeline_logger,
    set_pipeline_logger,
)


app = FastAPI()
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
    return PLAYGROUND_HTML


PLAYGROUND_HTML = """
<!doctype html>
<html>
<head>
  <title>Luvio Playground</title>
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

    <div class="shell">
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
              Type a message or record audio, then send it through the pipeline.
            </div>
          </div>
        </div>
      </main>

      <div class="composer-wrap">
        <div class="composer">
          <textarea
            class="text-input"
            id="textInput"
            rows="1"
            placeholder="Type your message..."
          ></textarea>
          <div class="composer-row">
            <div class="hint" id="hint">Type and press Send, or use Start / Stop for voice.</div>
            <button type="button" class="secondary" id="sendText">Send</button>
            <button type="button" class="secondary" id="start">Start</button>
            <button type="button" id="stop" disabled>Stop</button>
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

<script>
let recorder;
let chunks = [];
let mediaStream = null;
let activeHoldingBubble = null;
let activeAudio = null;
let abortController = null;
let isProcessing = false;
let activeChatId = null;
let logsPinnedToBottom = true;
let ttsInProgress = false;
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

const app = document.getElementById("app");
const start = document.getElementById("start");
const stop = document.getElementById("stop");
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
  if (activeAudio) {
    activeAudio.pause();
    activeAudio.currentTime = 0;
    activeAudio.src = "";
    activeAudio = null;
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
  sendText.disabled = busy;
  textInput.disabled = busy;
  start.disabled = busy && recorder && recorder.state === "recording" ? false : busy;
  stop.disabled = !recorder || recorder.state !== "recording";
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

  activeAudio = new Audio(
    `data:${data.mime_type || "audio/wav"};base64,${data.audio_base64}`
  );

  await activeAudio.play();
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
    hint.innerText = "Type and press Send, or use Start / Stop for voice.";
  }
}

async function startHoldingResponse(transcript, profile, signal) {
  if (!activeHoldingBubble) return;

  try {
    const result = await fetch("/api/holding-response", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript, profile }),
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
    body: JSON.stringify({ transcript, profile }),
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
      profile
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
      profile
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

    const data = await runTextQueryWithHolding(
      transcript,
      chatId,
      profile,
      signal
    );

    appendLogs(data.logs);
    showAssistantResponse(data);

    if (data.response && !(data.spotify_playback?.action === "play")) {
      playResponseTts(data, transcript);
    }

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

    if (activeHoldingBubble) {
      activeHoldingBubble.innerText = "Something went wrong while processing the query.";
    } else {
      addMessage("assistant", "Something went wrong while processing the query.");
    }
  } finally {
    activeHoldingBubble = null;
    setComposerBusy(false);
    start.disabled = false;
    stop.disabled = true;
    if (!ttsInProgress) {
      if (spotifyNowPlaying) {
        status.innerText = "Playing music";
      } else {
        status.innerText = "Ready";
        hint.innerText = "Type and press Send, or use Start / Stop for voice.";
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

sendText.onclick = async () => {
  const transcript = textInput.value.trim();
  if (!transcript || isProcessing) return;
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
  status.innerText = "Recording";
  status.className = "status recording";
  hint.innerText = "Listening... Spotify paused while recording.";
};

stop.onclick = async () => {
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

      const data = await runVoiceQueryWithHolding(
        blob,
        chatId,
        profile,
        signal
      );

      appendLogs(data.logs);
      showAssistantResponse(data);

      if (data.response && !(data.spotify_playback?.action === "play")) {
        playResponseTts(data, data.transcript || "");
      }

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
      }
    } finally {
      activeHoldingBubble = null;
      setComposerBusy(false);
      if (!ttsInProgress) {
        if (spotifyNowPlaying) {
          status.innerText = "Playing music";
        } else {
          status.innerText = "Ready";
          hint.innerText = "Type and press Send, or use Start / Stop for voice.";
        }
      }
      abortController = null;
    }
  };
};

loadProfile();
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


@app.post("/api/query")
def query(request: TranscriptRequest):
    with pipeline_session() as pipeline_logger:
        result = orchestrator.process_query(
            request.transcript,
            chat_id=request.chat_id,
            intent=request.intent,
            profile=_profile_payload(request.profile),
        )
        result["logs"] = pipeline_logger.to_list()
        return result


@app.post("/api/voice-query")
async def voice_query(
    audio: UploadFile = File(...),
    chat_id: str | None = Form(default=None),
):
    audio_bytes = await audio.read()

    with pipeline_session() as pipeline_logger:
        result = orchestrator.process_voice_query(
            audio_bytes=audio_bytes,
            mime_type=audio.content_type or "audio/webm",
            chat_id=chat_id,
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
        )
        result["logs"] = pipeline_logger.to_list()
        return result
