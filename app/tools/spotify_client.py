import json
import time
import urllib.parse

import httpx

from app.config import (
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_MARKET,
    SPOTIFY_REDIRECT_URI,
)
from app.conversation.responder import generate_response
from app.storage.spotify_token_store import SpotifyTokenStore
from app.utils.pipeline_log import pipeline_complete, pipeline_start

ACCOUNTS_BASE = "https://accounts.spotify.com"
API_BASE = "https://api.spotify.com/v1"

SPOTIFY_SCOPES = " ".join(
    [
        "streaming",
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
    ]
)

SPOTIFY_ACTION_PROMPT = """Extract the Spotify action from the user message.

Return JSON only with this shape:
{{"action":"play|pause|next|previous|resume|search|now_playing","query":""}}

Rules:
- play: user wants to play a specific song, artist, album, or playlist
- pause: user wants to pause playback
- next: skip to next track
- previous: go to previous track
- resume: continue playback without naming a track
- search: user wants to find music but not necessarily play it
- now_playing: user asks what is currently playing
- query: only the song, artist, or album name. Remove phrases like "on spotify", "play", "gana", "gaana", "bajao", "song".
- Keep Hindi/transliterated song titles as-is when present.

User message:
{transcript}
"""


class SpotifyClient:

    def __init__(self):
        self.tokens = SpotifyTokenStore()
        self._app_token: dict | None = None

    def is_configured(self) -> bool:
        return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)

    def is_connected(self) -> bool:
        return self.tokens.is_connected()

    def has_streaming_scope(self) -> bool:
        stored = self.tokens.load() or {}
        scope = stored.get("scope", "")
        return "streaming" in scope

    def get_access_token(self) -> str | None:
        return self._get_user_access_token()

    def authorization_url(self) -> str:
        params = {
            "client_id": SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": SPOTIFY_REDIRECT_URI,
            "scope": SPOTIFY_SCOPES,
            "show_dialog": "true" if not self.has_streaming_scope() else "false",
        }
        query = urllib.parse.urlencode(params)
        return f"{ACCOUNTS_BASE}/authorize?{query}"

    def exchange_code(self, code: str) -> dict:
        if self.tokens.is_connected() and self.has_streaming_scope():
            return self.tokens.load() or {}

        response = httpx.post(
            f"{ACCOUNTS_BASE}/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
                "client_id": SPOTIFY_CLIENT_ID,
                "client_secret": SPOTIFY_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20.0,
        )

        if response.status_code == 400 and self.tokens.is_connected():
            return self.tokens.load() or {}

        response.raise_for_status()
        payload = response.json()
        payload["expires_at"] = int(time.time()) + int(payload.get("expires_in", 3600))
        return self.tokens.save(payload)

    def disconnect(self) -> None:
        self.tokens.clear()

    def play_uri(self, uri: str, device_id: str) -> None:
        self._user_request(
            "PUT",
            "/me/player/play",
            params={"device_id": device_id},
            json={"uris": [uri]},
        )

    def handle_user_request(self, transcript: str) -> dict:
        if not self.is_configured():
            return {
                "message": (
                    "Spotify credentials are missing. "
                    "Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env."
                ),
                "playback": None,
            }

        action = self._parse_action(transcript)
        pipeline_start(
            "tool.spotify.action",
            "Parsed Spotify action",
            action,
        )

        try:
            if action["action"] == "play":
                outcome = self._play(action.get("query", ""))
            elif action["action"] == "pause":
                outcome = self._pause()
            elif action["action"] == "next":
                outcome = self._skip_next()
            elif action["action"] == "previous":
                outcome = self._skip_previous()
            elif action["action"] == "resume":
                outcome = self._resume()
            elif action["action"] == "now_playing":
                outcome = self._now_playing()
            elif action["action"] == "search":
                outcome = self._search(action.get("query", ""))
            else:
                outcome = self._search(action.get("query", transcript))
        except SpotifyAuthRequired as exc:
            outcome = {
                "message": str(exc),
                "playback": {"action": "connect"},
            }
        except SpotifyApiError as exc:
            outcome = {
                "message": str(exc),
                "playback": None,
            }

        pipeline_complete(
            "tool.spotify.action",
            "Spotify action completed",
            {
                "result_preview": outcome["message"][:160],
                "playback_action": (outcome.get("playback") or {}).get("action"),
            },
        )
        return outcome

    def _parse_action(self, transcript: str) -> dict:
        raw = generate_response(
            SPOTIFY_ACTION_PROMPT.format(transcript=transcript)
        ).strip()

        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"action": "play", "query": self._clean_query(transcript)}

        action = str(parsed.get("action", "play")).strip().lower()
        query = self._clean_query(str(parsed.get("query", "")).strip())

        valid = {
            "play",
            "pause",
            "next",
            "previous",
            "resume",
            "search",
            "now_playing",
        }

        if action not in valid:
            action = "play"
            if not query:
                query = self._clean_query(transcript)

        return {"action": action, "query": query}

    @staticmethod
    def _clean_query(query: str) -> str:
        cleaned = query.strip()
        for phrase in (
            "on spotify",
            "spotify par",
            "spotify pe",
            "spotify",
            "play ",
            "gana bajao",
            "gaana bajao",
            "song bajao",
            "bajao",
        ):
            cleaned = cleaned.replace(phrase, " ")
        return " ".join(cleaned.split())

    def _play(self, query: str) -> dict:
        if not query:
            return {
                "message": "Tell me which song or artist you want to play.",
                "playback": None,
            }

        tracks = self.search_tracks(query, limit=10)
        if not tracks:
            return {
                "message": f"I couldn't find '{query}' on Spotify.",
                "playback": None,
            }

        track = tracks[0]
        playback = {
            "action": "play",
            "tracks": tracks,
            "index": 0,
        }

        return {
            "message": f"Playing {track['label']} in the playground.",
            "playback": playback,
        }

    def _pause(self) -> dict:
        return {
            "message": "Paused playback in the playground.",
            "playback": {"action": "pause"},
        }

    def _resume(self) -> dict:
        return {
            "message": "Resumed playback in the playground.",
            "playback": {"action": "resume"},
        }

    def _skip_next(self) -> dict:
        return {
            "message": "Playing the next track in the playground.",
            "playback": {"action": "next"},
        }

    def _skip_previous(self) -> dict:
        return {
            "message": "Playing the previous track in the playground.",
            "playback": {"action": "previous"},
        }

    def _now_playing(self) -> dict:
        return {
            "message": "Checking what is playing in the playground.",
            "playback": {"action": "now_playing"},
        }

    def _search(self, query: str) -> dict:
        if not query:
            return {
                "message": "Tell me what you'd like to search for on Spotify.",
                "playback": None,
            }

        tracks = self.search_tracks(query, limit=5)
        if not tracks:
            return {
                "message": f"I couldn't find any Spotify tracks for '{query}'.",
                "playback": None,
            }

        lines = [
            f"{index}. {track['label']}"
            for index, track in enumerate(tracks, start=1)
        ]

        return {
            "message": "Here are the top Spotify matches:\n" + "\n".join(lines),
            "playback": {
                "action": "play",
                "tracks": tracks,
                "index": 0,
            },
        }

    def search_tracks(
        self,
        query: str,
        limit: int = 5,
        playable_only: bool = False,
    ) -> list[dict]:
        params = {
            "q": query,
            "type": "track",
            "limit": limit,
            "market": SPOTIFY_MARKET,
        }
        response = self._app_request("GET", "/search", params=params)
        items = response.json().get("tracks", {}).get("items", [])

        matches = []
        for item in items:
            track = self._track_payload(item)
            if playable_only and not track.get("preview_url"):
                continue
            matches.append(track)

        return matches

    @staticmethod
    def _track_payload(item: dict) -> dict:
        artists = ", ".join(
            artist.get("name", "")
            for artist in item.get("artists", [])
        )
        name = item.get("name", "Unknown track")
        album = item.get("album") or {}
        images = album.get("images") or []
        track_id = item.get("id", "")

        return {
            "track_id": track_id,
            "uri": item.get("uri", ""),
            "label": f"{name} by {artists}",
            "name": name,
            "artists": artists,
            "url": (item.get("external_urls") or {}).get("spotify", ""),
            "preview_url": item.get("preview_url") or "",
            "image_url": images[0]["url"] if images else "",
            "embed_url": (
                f"https://open.spotify.com/embed/track/{track_id}"
                if track_id
                else ""
            ),
        }

    def _user_request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> httpx.Response:
        token = self._get_user_access_token()
        if not token:
            raise SpotifyAuthRequired(
                "Spotify login is required once to play songs in the playground."
            )

        response = httpx.request(
            method,
            f"{API_BASE}{path}",
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
        )

        if response.status_code == 401:
            self.tokens.clear()
            raise SpotifyAuthRequired(
                "Spotify login expired. Reconnect once to keep playing in the playground."
            )

        if response.status_code >= 400:
            message = self._format_error(response)
            if response.status_code == 403 and "PREMIUM" in response.text.upper():
                raise SpotifyApiError(
                    "Spotify Premium is required to play full songs in the playground."
                )
            raise SpotifyApiError(message)

        return response

    def _app_request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> httpx.Response:
        token = self._get_app_access_token()
        response = httpx.request(
            method,
            f"{API_BASE}{path}",
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
        )

        if response.status_code >= 400:
            raise SpotifyApiError(self._format_error(response))

        return response

    def _get_app_access_token(self) -> str:
        if self._app_token and self._app_token["expires_at"] > time.time() + 30:
            return self._app_token["access_token"]

        response = httpx.post(
            f"{ACCOUNTS_BASE}/api/token",
            data={
                "grant_type": "client_credentials",
                "client_id": SPOTIFY_CLIENT_ID,
                "client_secret": SPOTIFY_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        self._app_token = {
            "access_token": payload["access_token"],
            "expires_at": int(time.time()) + int(payload.get("expires_in", 3600)),
        }
        return self._app_token["access_token"]

    def _get_user_access_token(self) -> str | None:
        stored = self.tokens.load()
        if not stored:
            return None

        if stored.get("expires_at", 0) > time.time() + 30:
            return stored["access_token"]

        refresh_token = stored.get("refresh_token")
        if not refresh_token:
            return None

        response = httpx.post(
            f"{ACCOUNTS_BASE}/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": SPOTIFY_CLIENT_ID,
                "client_secret": SPOTIFY_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20.0,
        )

        if response.status_code >= 400:
            self.tokens.clear()
            return None

        payload = response.json()
        payload["refresh_token"] = refresh_token
        payload["expires_at"] = int(time.time()) + int(payload.get("expires_in", 3600))
        if not payload.get("scope"):
            payload["scope"] = stored.get("scope", "")
        saved = self.tokens.save(payload)
        return saved["access_token"]

    @staticmethod
    def _format_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        message = payload.get("error", {}).get("message")
        if message:
            return f"Spotify API error: {message}"

        if isinstance(payload.get("error"), str):
            return f"Spotify API error: {payload['error']}"

        return f"Spotify API error ({response.status_code})."


class SpotifyAuthRequired(Exception):
    pass


class SpotifyApiError(Exception):
    pass
