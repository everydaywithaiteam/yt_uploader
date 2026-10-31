"""YouTube Data API v3 calls: auth, upload, thumbnail, captions, playlist."""
import os
import random
import sys
import time
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # captions, playlists, channel check
]
RETRY_STATUS = {500, 502, 503, 504}
CHUNK = 16 * 1024 * 1024


def get_service(creds_dir: str, expected_channel_id: Optional[str]):
    secret = os.path.join(creds_dir, "client_secret.json")
    token = os.path.join(creds_dir, "token.json")
    creds = None
    if os.path.exists(token):
        creds = Credentials.from_authorized_user_file(token, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"Saved login could not be refreshed ({e}); signing in again.")
            creds = None
    if not creds or not creds.valid:
        if not os.path.exists(secret):
            sys.exit(f"Missing {secret}. See README.md > One-time setup.")
        print("Opening browser for Google sign-in. Pick the Everyday With AI channel when asked.")
        flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
    with open(token, "w") as f:
        f.write(creds.to_json())
    os.chmod(token, 0o600)

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    resp = yt.channels().list(part="snippet", mine=True).execute()
    channels = resp.get("items", [])
    if not channels:
        sys.exit("Signed-in account has no YouTube channel.")
    ch = channels[0]
    if expected_channel_id and ch["id"] != expected_channel_id:
        os.remove(token)
        sys.exit(f"Signed in to channel '{ch['snippet']['title']}' ({ch['id']}), expected "
                 f"{expected_channel_id}. Token removed; re-run and choose the right channel.")
    print(f"Authenticated as channel: {ch['snippet']['title']} ({ch['id']})")
    return yt


def _execute_resumable(request, label: str):
    response, retries = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"\r  {label}: {pct}%", end="", flush=True)
        except HttpError as e:
            if e.resp.status not in RETRY_STATUS or retries >= 8:
                raise
            retries += 1
            wait = min(60, 2 ** retries) + random.random()
            print(f"\n  server error {e.resp.status}, retry {retries} in {wait:.0f}s")
            time.sleep(wait)
        except (ConnectionError, TimeoutError, OSError) as e:
            if retries >= 8:
                raise
            retries += 1
            wait = min(60, 2 ** retries) + random.random()
            print(f"\n  network error ({e}), retry {retries} in {wait:.0f}s")
            time.sleep(wait)
    print(f"\r  {label}: 100%")
    return response


def upload_video(yt, path: str, body: dict, notify_subscribers: bool) -> str:
    media = MediaFileUpload(path, chunksize=CHUNK, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media,
                             notifySubscribers=notify_subscribers)
    resp = _execute_resumable(req, "video")
    return resp["id"]


def set_thumbnail(yt, video_id: str, path: str):
    yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(path)).execute()


def upload_captions(yt, video_id: str, path: str, language: str, name: str = ""):
    body = {"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}}
    media = MediaFileUpload(path, mimetype="application/octet-stream", resumable=True)
    req = yt.captions().insert(part="snippet", body=body, media_body=media)
    _execute_resumable(req, "captions")


def find_playlist(yt, name: str) -> Optional[str]:
    wanted = name.strip().lower()
    req = yt.playlists().list(part="snippet", mine=True, maxResults=50)
    while req is not None:
        resp = req.execute()
        for pl in resp.get("items", []):
            if pl["snippet"]["title"].strip().lower() == wanted:
                return pl["id"]
        req = yt.playlists().list_next(req, resp)
    return None


def add_to_playlist(yt, video_id: str, playlist_id: str):
    yt.playlistItems().insert(part="snippet", body={"snippet": {
        "playlistId": playlist_id,
        "resourceId": {"kind": "youtube#video", "videoId": video_id},
    }}).execute()
