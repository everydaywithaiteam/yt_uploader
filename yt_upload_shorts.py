#!/usr/bin/env python3
"""Upload a batch of YouTube Shorts from a yt_shorts folder, one after another, as private.

Usage (through the ./upload wrapper):
  ./upload 13 --shorts --dry-run                 # plan for video 13's yt_shorts/
  ./upload 13 --shorts --long-url sXwF7qQpIOY    # link each Short to the long-form video
  ./upload 13 --shorts --no-link                 # no long-form link
  ./upload "/path/to/yt_shorts" --shorts         # explicit folder (e.g. a one-off Short)
  ./upload 13 --shorts --only 2,5                # just Shorts 2 and 5

Metadata comes from the highest youtube-shorts-package-vN.md in the folder (## Short N ->
### Title / ### Description / ### Tags). Videos are the top-level .mp4/.mov files, uploaded in
file-name order. Files are uploaded as they are: no audio normalization.
"""
import argparse
import datetime as dt
import json
import os
import sys
from typing import List, Optional

from ytu import metadata as md
from ytu import package as pk
from ytu import shorts as sh
from yt_upload import CONFIG_PATH, CREDS_DIR, HERE, STATE_PATH, fmt_secs, load_json, video_duration

SHORTS_STATE_PATH = os.path.join(HERE, "state", "shorts_uploads.json")
MAX_SHORT_SECONDS = 180
QUOTA_REASONS = {"quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded", "rateLimitExceeded"}


def save_shorts_state(state):
    os.makedirs(os.path.dirname(SHORTS_STATE_PATH), exist_ok=True)
    with open(SHORTS_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def resolve_shorts_dir(arg: Optional[str], root: str, state: dict) -> str:
    if arg and os.path.isdir(os.path.expanduser(arg)):
        path = os.path.abspath(os.path.expanduser(arg))
        found = sh.find_shorts_dir(path)
        if not found:
            sys.exit(f"No {sh.PACKAGE_PREFIX}-vN.md in {path} or its {sh.SHORTS_DIR}/ folder.")
        return found
    dirs = pk.list_video_dirs(root)
    if arg:
        if arg.isdigit():
            hits = [d for d in dirs if pk.video_number(os.path.basename(d)) == int(arg)]
        else:
            hits = [d for d in dirs if arg.lower() in os.path.basename(d).lower()]
        if len(hits) != 1:
            sys.exit(f"Could not match '{arg}' to one folder in {root}: {[os.path.basename(h) for h in hits]}")
        found = sh.find_shorts_dir(hits[0])
        if not found:
            sys.exit(f"No {sh.SHORTS_DIR}/{sh.PACKAGE_PREFIX}-vN.md in {os.path.basename(hits[0])}.")
        return found
    # No argument: newest video folder whose yt_shorts/ has videos not uploaded yet.
    for d in reversed(dirs):
        found = sh.find_shorts_dir(d)
        if found and any(v not in state for v in sh.find_short_videos(found)):
            return found
    sys.exit("No video folder with un-uploaded Shorts found. Pass a number or a folder path.")


def parent_video_dir(shorts_dir: str) -> Optional[str]:
    if os.path.basename(shorts_dir) == sh.SHORTS_DIR:
        return os.path.dirname(shorts_dir)
    return None


def parse_only(value: Optional[str]) -> Optional[set]:
    if not value:
        return None
    try:
        return {int(x) for x in value.replace(" ", "").split(",") if x}
    except ValueError:
        sys.exit(f"--only {value}: expected numbers like 2,5")


def quota_error(e) -> bool:
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        return False
    if not isinstance(e, HttpError):
        return False
    try:
        reasons = {err.get("reason") for err in json.loads(e.content).get("error", {}).get("errors", [])}
    except (ValueError, AttributeError):
        reasons = set()
    return bool(reasons & QUOTA_REASONS)


def validate(item: sh.ShortItem, duration, dims, description: str):
    errors: List[str] = []
    warnings: List[str] = []
    m = item.meta
    if not m.title:
        errors.append("No ### Title.")
    elif len(m.title) > 100:
        errors.append(f"Title is {len(m.title)} chars (max 100).")
    if "<" in m.title or ">" in m.title:
        errors.append("Title contains < or >, which YouTube rejects.")
    if len(description) > 5000:
        errors.append(f"Description is {len(description)} chars (max 5000).")
    if "<" in description or ">" in description:
        errors.append("Description contains < or >, which YouTube rejects.")
    if not m.description:
        warnings.append("No ### Description.")
    for line in md.find_placeholders(m.description):
        warnings.append(f"Description line looks like an author note: \"{line}\"")
    tag_len = sum(len(t) + (2 if " " in t else 0) for t in m.tags) + max(0, len(m.tags) - 1)
    if tag_len > 500:
        errors.append(f"Tags total {tag_len} chars (max 500).")
    if duration and duration > MAX_SHORT_SECONDS:
        warnings.append(f"Video is {fmt_secs(duration)}; over 3:00 it is not treated as a Short.")
    if dims and dims[0] > dims[1]:
        warnings.append(f"Video is {dims[0]}x{dims[1]} (landscape); it is not treated as a Short.")
    return errors, warnings


def video_dims(path: str):
    import shutil
    import subprocess
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height", "-of", "csv=p=0", path],
                             capture_output=True, text=True, check=True).stdout.strip()
        w, h = out.split(",")[:2]
        return int(w), int(h)
    except (subprocess.CalledProcessError, ValueError):
        return None


def build_description(meta: sh.ShortMeta, long_url: Optional[str]) -> str:
    parts = [meta.description.strip()]
    if long_url:
        parts.append(f"Watch the full video: {long_url}")
    return "\n\n".join(p for p in parts if p)


def main(argv: Optional[List[str]] = None):
    ap = argparse.ArgumentParser(prog="upload --shorts", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", help="video number (13), name fragment, or a folder path")
    ap.add_argument("--dry-run", action="store_true", help="print the upload plan and stop")
    link = ap.add_mutually_exclusive_group()
    link.add_argument("--long-url", metavar="URL", help="long-form video to link (URL or video ID)")
    link.add_argument("--no-link", action="store_true", help="don't link a long-form video")
    ap.add_argument("--only", metavar="N[,N…]", help="upload only these short numbers")
    ap.add_argument("--privacy", choices=["private", "unlisted", "public"], help="default: private")
    ap.add_argument("--playlist", metavar="NAME", help="add to this playlist instead of the config default")
    ap.add_argument("--no-playlist", action="store_true", help="don't add to any playlist")
    ap.add_argument("--publish-at", metavar="'YYYY-MM-DD[ HH:MM]'",
                    help="schedule the first Short (config timezone; date only = default_publish_time); "
                         "later ones follow --every-days apart")
    ap.add_argument("--every-days", type=int, default=1, metavar="N",
                    help="days between scheduled Shorts (default 1)")
    ap.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompts")
    ap.add_argument("--force", action="store_true", help="upload despite errors or previous uploads")
    args = ap.parse_args(argv)

    config = load_json(CONFIG_PATH, {})
    state = load_json(SHORTS_STATE_PATH, {})
    root = os.path.expanduser(config["videos_root"])
    shorts_dir = resolve_shorts_dir(args.folder, root, state)
    package_path = sh.latest_package(shorts_dir)
    metas = sh.parse_package(package_path)
    if not metas:
        sys.exit(f"No '## Short N' sections in {os.path.basename(package_path)}.")
    videos = sh.find_short_videos(shorts_dir)
    if not videos:
        sys.exit(f"No .mp4/.mov files in {shorts_dir}.")
    items, pair_errors = sh.pair(metas, videos)
    if pair_errors:
        print("\n".join(f"ERROR:   {e}" for e in pair_errors))
        print("Videos:   " + ", ".join(os.path.basename(v) for v in videos))
        sys.exit(1)
    only = parse_only(args.only)
    if only:
        unknown = only - {i.meta.number for i in items}
        if unknown:
            sys.exit(f"--only: no video file for short(s) {sorted(unknown)}.")
        items = [i for i in items if i.meta.number in only]

    # Long-form link: flag > the parent video's long-form upload recorded by ./upload > none.
    long_url, link_source = None, None
    if args.long_url:
        long_url = sh.normalize_youtube_link(args.long_url)
        if not long_url:
            sys.exit(f"--long-url {args.long_url}: not a YouTube link or video ID.")
        link_source = "--long-url"
    elif not args.no_link:
        parent = parent_video_dir(shorts_dir)
        prev = load_json(STATE_PATH, {}).get(parent) if parent else None
        if prev:
            long_url, link_source = f"https://youtu.be/{prev['video_id']}", \
                f"long-form upload of '{os.path.basename(parent)}' (\"{prev.get('title', '')}\")"
        if not args.yes and not args.dry_run:
            hint = f" [{long_url}]" if long_url else ""
            ans = input(f"\nLong-form video to link{hint} (Enter = {'accept' if long_url else 'none'}, "
                        "'-' = none, or paste a link): ").strip()
            if ans == "-":
                long_url, link_source = None, None
            elif ans:
                long_url = sh.normalize_youtube_link(ans)
                if not long_url:
                    sys.exit(f"'{ans}' is not a YouTube link or video ID.")
                link_source = "entered"

    privacy = args.privacy or config.get("default_privacy", "private")
    schedule = {}  # short number -> (local label, UTC RFC3339)
    if args.publish_at:
        from ytu import schedule as sched
        if privacy != "private":
            sys.exit("--publish-at needs private uploads (YouTube flips them public at the scheduled time).")
        if args.every_days < 1:
            sys.exit("--every-days must be 1 or more.")
        start = sched.parse_local(args.publish_at, config.get("timezone", "UTC"),
                                  config.get("default_publish_time", sched.DEFAULT_TIME))
        for k, it in enumerate(items):
            when = sched.add_days(start, k * args.every_days)
            schedule[it.meta.number] = (sched.label(when), sched.to_utc(when))
    playlist_name = None if args.no_playlist else (
        args.playlist or config.get("shorts_playlist", config.get("default_playlist")))
    lang = config.get("language", "en")

    # ---- plan ----
    print(f"\nFolder:      {os.path.relpath(shorts_dir, root) if shorts_dir.startswith(root) else shorts_dir}")
    print(f"Package:     {os.path.basename(package_path)}  ({len(metas)} shorts)")
    print(f"Long-form:   {long_url + '  (from ' + link_source + ')' if long_url else '— none'}")
    print(f"Privacy:     {privacy}" + (f", scheduled every {args.every_days} day(s) from {sched.label(start)} "
                                         f"({config.get('timezone')})" if schedule else ""))
    print(f"Playlist:    {playlist_name or '— none'}")
    print("Audio:       uploaded as-is (no normalization)")

    any_errors = False
    todo_items = []
    for idx, item in enumerate(items, 1):
        path = item.video_path
        duration, dims = video_duration(path), video_dims(path)
        description = build_description(item.meta, long_url)
        errors, warnings = validate(item, duration, dims, description)
        prev = state.get(path)
        size = f"{os.path.getsize(path) / 1e6:.0f} MB"
        shape = f"{dims[0]}x{dims[1]}" if dims else "?"
        print(f"\n[{idx}/{len(items)}] Short {item.meta.number}: {item.meta.title}")
        print(f"  File:  {os.path.basename(path)}  {size}  {fmt_secs(duration) if duration else '?'}  {shape}")
        if item.meta.number in schedule:
            print(f"  Publishes: {schedule[item.meta.number][0]}")
        print(f"  Tags ({len(item.meta.tags)}): {', '.join(item.meta.tags)}")
        print("  Description:\n" + "\n".join("    " + l for l in description.splitlines()))
        if prev:
            print(f"  ALREADY UPLOADED: https://youtu.be/{prev['video_id']} on {prev['uploaded_at']}"
                  + ("" if args.force else " (skipped; --force to upload again)"))
        for w in warnings:
            print(f"  WARNING: {w}")
        for e in errors:
            print(f"  ERROR:   {e}")
        any_errors = any_errors or bool(errors)
        if not prev or args.force:
            todo_items.append((item, description))

    if any_errors and not args.force:
        sys.exit("\nFix the errors above in the package file (or pass --force).")
    if not todo_items:
        print("\nNothing to upload: every Short here is already uploaded.")
        return
    if args.dry_run:
        print(f"\nDry run: would upload {len(todo_items)} Short(s) in the order above. Nothing uploaded.")
        return
    if not args.yes and input(f"\nUpload {len(todo_items)} Short(s) now? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled.")

    from ytu import youtube as yt_api  # deferred so --dry-run works without credentials
    yt = yt_api.get_service(CREDS_DIR, config.get("channel_id"))
    playlist_id = None
    playlist_todo = None
    if playlist_name:
        try:
            playlist_id = yt_api.find_playlist(yt, playlist_name)
            if not playlist_id:
                playlist_todo = f"Playlist '{playlist_name}' not found on channel; add the Shorts manually"
        except Exception as e:
            playlist_todo = f"Add the Shorts to '{playlist_name}' manually ({e})"

    done, stopped = [], None
    for idx, (item, description) in enumerate(todo_items, 1):
        m = item.meta
        body = {
            "snippet": {"title": m.title, "description": description, "tags": m.tags,
                        "categoryId": "28", "defaultLanguage": lang, "defaultAudioLanguage": lang},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "embeddable": True,
                       "containsSyntheticMedia": config.get("contains_synthetic_media", False)},
        }
        if m.number in schedule:
            body["status"]["publishAt"] = schedule[m.number][1]
        print(f"\n[{idx}/{len(todo_items)}] Uploading Short {m.number}: {m.title}")
        try:
            video_id = yt_api.upload_video(yt, item.video_path, body, config.get("notify_subscribers", True))
        except Exception as e:
            stopped = (m.number, e)
            break
        print(f"  Uploaded: https://youtu.be/{video_id}")
        record = {"video_id": video_id, "title": m.title, "short_number": m.number, "privacy": privacy,
                  "publish_at": schedule.get(m.number, (None, None))[1], "long_form_url": long_url, "package": package_path,
                  "uploaded_at": dt.datetime.now().isoformat(timespec="seconds")}
        state[item.video_path] = record
        save_shorts_state(state)  # save after each so a re-run continues where it stopped
        todo = []
        if playlist_id:
            try:
                yt_api.add_to_playlist(yt, video_id, playlist_id)
                print(f"  Added to playlist '{playlist_name}'.")
            except Exception as e:
                todo.append(f"Add to playlist '{playlist_name}' manually ({e})")
        record["todo"] = todo
        save_shorts_state(state)
        done.append((m, video_id, todo))

    # ---- report ----
    print("\n==== Shorts uploaded ====")
    for m, video_id, _ in done:
        print(f"  Short {m.number}: https://youtu.be/{video_id}   "
              f"Studio: https://studio.youtube.com/video/{video_id}/edit   {m.title}"
              + (f"   publishes {schedule[m.number][0]}" if m.number in schedule else ""))
    if stopped:
        num, e = stopped
        why = "YouTube API quota / upload limit reached" if quota_error(e) else f"error: {e}"
        left = [i.meta.number for i, _ in todo_items[len(done):]]
        print(f"\nSTOPPED at Short {num} ({why}). Not uploaded: {left}. "
              "Re-run the same command later; uploaded Shorts are skipped.")

    print("\nManual steps left:")
    if long_url and done:
        print(f"  - In Studio, set each Short's 'Related video' to {long_url} "
              "(Details > Related video; the API can't set it)")
    if playlist_todo:
        print(f"  - {playlist_todo}")
    for m, _, todo in done:
        for t in todo:
            print(f"  - Short {m.number}: {t}")
    if privacy == "private" and done and not schedule:
        print("  - Shorts are private: set visibility / schedule each in Studio when ready")
    if stopped:
        sys.exit(1)


if __name__ == "__main__":
    main()
