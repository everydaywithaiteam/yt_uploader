#!/usr/bin/env python3
"""Upload an Everyday With AI long-form video to YouTube from its production package.

Usage:
  ./upload                      # newest video folder not yet uploaded
  ./upload 12                   # "video 12 - ..." folder
  ./upload "/path/to/video dir" # explicit folder
  ./upload 12 --dry-run         # show what would be uploaded, touch nothing
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional

from ytu import chapters as chap
from ytu import metadata as md
from ytu import package as pk

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "state", "uploads.json")
CREDS_DIR = os.path.join(HERE, "credentials")
THUMB_MAX_BYTES = 2 * 1024 * 1024


def load_json(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def resolve_folder(arg: Optional[str], root: str, state: dict) -> str:
    if arg and os.path.isdir(os.path.expanduser(arg)):
        return os.path.abspath(os.path.expanduser(arg))
    dirs = pk.list_video_dirs(root)
    if arg:
        if arg.isdigit():
            hits = [d for d in dirs if pk.video_number(os.path.basename(d)) == int(arg)]
        else:
            hits = [d for d in dirs if arg.lower() in os.path.basename(d).lower()]
        if len(hits) != 1:
            sys.exit(f"Could not match '{arg}' to one folder in {root}: {[os.path.basename(h) for h in hits]}")
        return hits[0]
    # No argument: newest folder that has a package and has not been uploaded.
    for d in reversed(dirs):
        if d in state:
            continue
        if pk.latest_versioned(d, "yt_production_package"):
            return d
    sys.exit("No un-uploaded video folder with a yt_production_package_vN found.")


def video_duration(path: str) -> Optional[float]:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", path],
                             capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError):
        return None


def fmt_secs(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def validate(meta: md.UploadMetadata, pkg: pk.Package, duration: Optional[float],
             thumbnail: Optional[str], use_captions: bool):
    errors: List[str] = []
    warnings: List[str] = []

    if not pkg.video_path:
        errors.append("No final video file (.mp4/.mov) found in the video folder.")
    elif len(pkg.video_candidates) > 1:
        others = [os.path.relpath(p, pkg.video_dir) for p in pkg.video_candidates if p != pkg.video_path]
        warnings.append(f"Several video files found; using the FCP/newest one. Others: {others}")

    if not meta.title:
        errors.append("No title found under '## Recommended title'.")
    elif len(meta.title) > 100:
        errors.append(f"Title is {len(meta.title)} chars (max 100).")
    if "<" in meta.title or ">" in meta.title:
        errors.append("Title contains < or >, which YouTube rejects.")

    desc = meta.description
    if len(desc) > 5000:
        errors.append(f"Description is {len(desc)} chars (max 5000).")
    if "<" in desc or ">" in desc:
        errors.append("Description contains < or >, which YouTube rejects.")
    for line in md.find_placeholders(meta.description_body):
        warnings.append(f"Description line looks like an author note, not viewer copy: \"{line}\"")

    # YouTube chapter rules: first at 0:00, at least 3, each at least 10s long, ascending.
    ch = meta.chapters
    if ch:
        if ch[0].seconds != 0:
            errors.append("First chapter must start at 00:00.")
        if len(ch) < 3:
            errors.append("YouTube needs at least 3 chapters.")
        for a, b in zip(ch, ch[1:]):
            if b.seconds - a.seconds < 10:
                errors.append(f"Chapter '{a.title}' is shorter than 10s or out of order.")
        if duration:
            late = [c for c in ch if c.seconds >= duration - 10]
            if late:
                errors.append(
                    f"Video is {fmt_secs(duration)} but chapters go to {ch[-1].timestamp}; "
                    f"{len(late)} chapter(s) start at or past the end: "
                    + ", ".join(f"{c.timestamp} {c.title}" for c in late)
                    + ". Chapters look like they came from the script plan, not the final edit.")
    else:
        warnings.append("No chapters found.")

    tag_len = sum(len(t) + (2 if " " in t else 0) for t in meta.tags) + max(0, len(meta.tags) - 1)
    if tag_len > 500:
        errors.append(f"Tags total {tag_len} chars (max 500).")

    if meta.category_id is None:
        warnings.append(f"Unknown category '{meta.settings.get('category')}', defaulting to Science & Technology.")
    if meta.made_for_kids is None:
        warnings.append("Audience not stated, defaulting to 'Not made for kids'.")

    if not thumbnail:
        warnings.append("No thumbnail*.png/jpg in the package; YouTube will auto-pick a frame.")
    if use_captions and not pkg.captions_path:
        warnings.append("No .srt next to the video; captions will not be uploaded.")
    return errors, warnings


def derive_chapters(meta: md.UploadMetadata, pkg: pk.Package):
    """Replace planned chapters with ones aligned to the final edit's captions.

    Returns (aligned rows for the report, source label, warnings).
    """
    if not pkg.captions_path:
        return None, None, ["No .srt found: keeping the planned chapters from the metadata."]
    warnings = []
    if pkg.script_path:
        sections, source = chap.sections_from_script(pkg.script_path), os.path.basename(pkg.script_path)
    elif pkg.prompter_path:
        sections, source = chap.sections_from_prompter(pkg.prompter_path, meta.chapters), os.path.basename(pkg.prompter_path)
        warnings.append("No production script: chapter boundaries were estimated from the teleprompter "
                        "text and may be off. Review them before publishing.")
    else:
        return None, None, ["No production script or teleprompter: keeping the planned chapters."]
    if not sections:
        return None, source, [f"No '## Section N' prose found in {source}: keeping the planned chapters."]

    aligned = chap.align(sections, chap.srt_words(pkg.captions_path), meta.chapters)
    if len(meta.chapters) != len(sections):
        warnings.append(f"Metadata has {len(meta.chapters)} chapters but the script has {len(sections)} "
                        "sections: chapter titles come from the script headings.")
    derived = chap.to_chapters(aligned)
    if not derived:
        warnings.append("Fewer than 3 chapters could be located in the captions: no chapters will be set.")
    for row in aligned:
        if row.seconds is not None and row.coverage < 0.5:
            warnings.append(f"Chapter '{row.title}' only {row.coverage:.0%} matched the script; check its start.")
    meta.chapters = derived
    return aligned, source, warnings


def prepare_thumbnail(path: str) -> str:
    if os.path.getsize(path) <= THUMB_MAX_BYTES:
        return path
    out = os.path.join(tempfile.mkdtemp(prefix="ytu_"), os.path.splitext(os.path.basename(path))[0] + ".jpg")
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", path, "--out", out],
                   check=True, capture_output=True)
    return out


def parse_publish_at(value: str, tz_name: str) -> str:
    from zoneinfo import ZoneInfo
    local = dt.datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz_name))
    if local <= dt.datetime.now(local.tzinfo):
        sys.exit(f"--publish-at {value} is in the past.")
    return local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", help="video folder path, number (12) or name fragment")
    ap.add_argument("--dry-run", action="store_true", help="print the upload plan and stop")
    ap.add_argument("--privacy", choices=["private", "unlisted", "public"], help="override config default")
    ap.add_argument("--publish-at", metavar="'YYYY-MM-DD HH:MM'",
                    help="schedule publish (local time from config timezone); uploads as private until then")
    ap.add_argument("--title", type=int, default=0, metavar="N", help="use alternate title N (1-based)")
    ap.add_argument("--thumbnail", type=int, default=1, metavar="N", help="use Nth thumbnail (default 1)")
    ap.add_argument("--planned-chapters", action="store_true",
                    help="use the metadata's chapter times as-is instead of aligning them to the .srt")
    ap.add_argument("--no-captions", action="store_true", help="skip uploading the .srt")
    ap.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--force", action="store_true", help="upload despite errors or a previous upload")
    ap.add_argument("--short", action="store_true", help="Shorts mode (not implemented yet)")
    args = ap.parse_args()

    if args.short:
        sys.exit("Shorts upload is TBD: define the shorts folder/metadata layout first.")

    config = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {})
    root = os.path.expanduser(config["videos_root"])

    folder = resolve_folder(args.folder, root, state)
    try:
        pkg = pk.load(folder)
    except FileNotFoundError as e:
        sys.exit(str(e))
    meta = md.parse(pkg.metadata_path)

    if args.title:
        if not 1 <= args.title <= len(meta.alt_titles):
            sys.exit(f"--title {args.title}: only {len(meta.alt_titles)} alternate titles.")
        meta.title = meta.alt_titles[args.title - 1]

    thumbnail = None
    if pkg.thumbnails:
        if not 1 <= args.thumbnail <= len(pkg.thumbnails):
            sys.exit(f"--thumbnail {args.thumbnail}: only {len(pkg.thumbnails)} thumbnails.")
        thumbnail = pkg.thumbnails[args.thumbnail - 1]

    aligned, chapter_source, chapter_warnings = (None, None, []) if args.planned_chapters \
        else derive_chapters(meta, pkg)

    use_captions = not args.no_captions and config.get("upload_captions", True)
    duration = video_duration(pkg.video_path) if pkg.video_path else None
    errors, warnings = validate(meta, pkg, duration, thumbnail, use_captions)
    warnings = chapter_warnings + warnings

    privacy = args.privacy or config.get("default_privacy", "private")
    publish_at = parse_publish_at(args.publish_at, config.get("timezone", "UTC")) if args.publish_at else None
    if publish_at:
        privacy = "private"
    playlist_name = config.get("playlist_overrides", {}).get(os.path.basename(folder)) \
        or (meta.playlist if meta.playlist and not md.find_placeholders(meta.playlist) else None) \
        or config.get("default_playlist")

    # ---- plan ----
    rel = lambda p: os.path.relpath(p, folder) if p else "—"
    print(f"\nFolder:      {os.path.basename(folder)}")
    print(f"Package:     {os.path.basename(pkg.package_dir)}  ({os.path.basename(pkg.metadata_path)})")
    size = f"{os.path.getsize(pkg.video_path) / 1e6:.0f} MB" if pkg.video_path else ""
    print(f"Video:       {rel(pkg.video_path)}  {size}  {fmt_secs(duration) if duration else ''}")
    print(f"Thumbnail:   {rel(thumbnail)}")
    print(f"Captions:    {rel(pkg.captions_path) if use_captions else 'skipped'}")
    print(f"Title:       {meta.title}")
    print(f"Privacy:     {privacy}" + (f", publishes {args.publish_at} ({config.get('timezone')})" if publish_at else ""))
    print(f"Category:    {meta.category_id or '28'}   Kids: {bool(meta.made_for_kids)}   Language: {meta.language or 'en'}")
    print(f"Playlist:    {playlist_name or '— (none set)'}")
    print(f"Tags ({len(meta.tags)}):   {', '.join(meta.tags)}")
    if aligned:
        print(f"\nChapters aligned from {os.path.basename(pkg.captions_path)} against {chapter_source}:")
        print(f"  {'planned':>8}  {'actual':>7}  {'match':>5}  title")
        for row in aligned:
            actual = fmt_secs(row.seconds) if row.seconds is not None else "—"
            print(f"  {row.planned or '':>8}  {actual:>7}  {row.coverage:>5.0%}  {row.title}"
                  + (f"   ({row.note})" if row.note else ""))
    print("\n---- description ----\n" + meta.description + "\n---------------------")

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR:   {e}")

    if folder in state and not args.force:
        prev = state[folder]
        sys.exit(f"\nAlready uploaded as https://youtu.be/{prev['video_id']} on {prev['uploaded_at']}. "
                 "Use --force to upload again.")
    if errors and not args.force:
        sys.exit("\nFix the errors above in the metadata file (or pass --force).")
    if args.dry_run:
        print("\nDry run: nothing uploaded.")
        return
    if not args.yes and input("\nUpload now? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled.")

    from ytu import youtube as yt_api  # deferred so --dry-run works without credentials
    yt = yt_api.get_service(CREDS_DIR, config.get("channel_id"))

    lang = meta.language or config.get("language", "en")
    body = {
        "snippet": {
            "title": meta.title,
            "description": meta.description,
            "tags": meta.tags,
            "categoryId": meta.category_id or "28",
            "defaultLanguage": lang,
            "defaultAudioLanguage": lang,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(meta.made_for_kids),
            "embeddable": True,
            "containsSyntheticMedia": config.get("contains_synthetic_media", False),
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at

    print("\nUploading…")
    video_id = yt_api.upload_video(yt, pkg.video_path, body, config.get("notify_subscribers", True))
    print(f"Uploaded: https://youtu.be/{video_id}")
    record = {"video_id": video_id, "title": meta.title, "privacy": privacy, "publish_at": publish_at,
              "metadata": pkg.metadata_path, "uploaded_at": dt.datetime.now().isoformat(timespec="seconds")}
    state[folder] = record
    save_state(state)  # save right away so a later failure can't cause a duplicate upload

    todo = []
    if thumbnail:
        try:
            yt_api.set_thumbnail(yt, video_id, prepare_thumbnail(thumbnail))
            print("Thumbnail set.")
        except Exception as e:
            todo.append(f"Set thumbnail manually ({e})")
    if use_captions and pkg.captions_path:
        try:
            yt_api.upload_captions(yt, video_id, pkg.captions_path, lang)
            print("Captions uploaded.")
        except Exception as e:
            todo.append(f"Upload captions manually ({e})")
    if playlist_name:
        try:
            pid = yt_api.find_playlist(yt, playlist_name)
            if pid:
                yt_api.add_to_playlist(yt, video_id, pid)
                print(f"Added to playlist '{playlist_name}'.")
            else:
                todo.append(f"Playlist '{playlist_name}' not found on channel; add manually")
        except Exception as e:
            todo.append(f"Add to playlist manually ({e})")
    else:
        todo.append("Add to a playlist (none set in metadata/config)")

    if meta.pinned_comment:
        todo.append("Post and pin the comment (API can't pin):\n      " + meta.pinned_comment)
    todo.append("Add end screen and cards (not available via API)")
    if len(pkg.thumbnails) > 1:
        todo.append("Optional: start a thumbnail Test & Compare with: "
                    + ", ".join(os.path.basename(t) for t in pkg.thumbnails))
    if privacy == "private" and not publish_at:
        todo.append("Video is private: set visibility / schedule in Studio when ready")

    record["todo"] = todo
    save_state(state)
    print(f"\nStudio: https://studio.youtube.com/video/{video_id}/edit")
    print("\nManual steps left:")
    for t in todo:
        print(f"  - {t}")


if __name__ == "__main__":
    main()
