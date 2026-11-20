"""Locate a yt_shorts folder, parse youtube-shorts-package-vN.md and pair shorts with video files."""
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ytu import metadata as md
from ytu import package as pk

SHORTS_DIR = "yt_shorts"
PACKAGE_PREFIX = "youtube-shorts-package"
YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass
class ShortMeta:
    number: int
    title: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class ShortItem:
    meta: ShortMeta
    video_path: str


def latest_package(shorts_dir: str) -> Optional[str]:
    """Highest youtube-shorts-package-vN.md (also accepts _vN)."""
    best = None
    for entry in os.listdir(shorts_dir):
        m = re.match(rf"^{re.escape(PACKAGE_PREFIX)}[-_]v(\d+)\.md$", entry, re.IGNORECASE)
        if m and (best is None or int(m.group(1)) > best[1]):
            best = (os.path.join(shorts_dir, entry), int(m.group(1)))
    return best[0] if best else None


def find_shorts_dir(path: str) -> Optional[str]:
    """`path` itself if it holds a shorts package, else its yt_shorts/ subfolder."""
    for d in (path, os.path.join(path, SHORTS_DIR)):
        if os.path.isdir(d) and latest_package(d):
            return d
    return None


def parse_package(path: str) -> List[ShortMeta]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    shorts: List[ShortMeta] = []
    blocks = re.split(r"^##\s+Short\s+(\d+)\s*$", text, flags=re.MULTILINE | re.IGNORECASE)
    # blocks = [preamble, "1", body1, "2", body2, ...]
    for num, body in zip(blocks[1::2], blocks[2::2]):
        subs = {}
        current = None
        for line in body.splitlines():
            m = re.match(r"^###\s+(.+?)\s*$", line)
            if m:
                current = m.group(1).strip().lower()
                subs[current] = []
            elif current is not None:
                subs[current].append(line)
        subs = {k: "\n".join(v).strip() for k, v in subs.items()}
        s = ShortMeta(number=int(num))
        s.title = next((md.strip_list_marker(l) for l in subs.get("title", "").splitlines() if l.strip()), "")
        desc = subs.get("description") or subs.get("short description") or ""
        s.description = md.md_to_plain(desc)
        raw = re.split(r"[,\n]", subs.get("tags", ""))
        s.tags = [md.strip_list_marker(t).lstrip("#") for t in raw if md.strip_list_marker(t)]
        shorts.append(s)
    return shorts


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def find_short_videos(shorts_dir: str) -> List[str]:
    """Top-level video files only (originals/ etc. are skipped), in file-name order."""
    files = [f for f in os.listdir(shorts_dir)
             if f.lower().endswith(pk.VIDEO_EXTS) and not f.startswith(".")
             and "-stage1" not in f.lower()]
    # Gling exports sit next to the raw recording as '<name>-export.mp4'; upload only the export.
    stems = {os.path.splitext(f)[0].lower() for f in files}
    files = [f for f in files if os.path.splitext(f)[0].lower() + "-export" not in stems]
    return [os.path.join(shorts_dir, f) for f in sorted(files, key=_natural_key)]


def short_number(path: str) -> Optional[int]:
    """The short's number from names like 'v13 3 - Short_…' or '3 Short_…'."""
    m = re.match(r"^(?:v\d+\s+)?(\d+)\b", os.path.basename(path), re.IGNORECASE)
    return int(m.group(1)) if m else None


def pair(metas: List[ShortMeta], videos: List[str]) -> Tuple[List[ShortItem], List[str]]:
    """Match video files to package entries. Returns (items in upload order, errors).

    If every file name starts with a short number that exists in the package, files are matched
    by that number (so a partial batch works). Otherwise they're matched by position, which
    needs the counts to agree.
    """
    by_num = {m.number: m for m in metas}
    nums = [short_number(v) for v in videos]
    if videos and all(n is not None and n in by_num for n in nums) and len(set(nums)) == len(nums):
        return [ShortItem(by_num[n], v) for n, v in zip(nums, videos)], []
    if len(metas) != len(videos):
        return [], [f"Package has {len(metas)} shorts but the folder has {len(videos)} video files, "
                    "and the file names don't carry short numbers to match them by."]
    return [ShortItem(m, v) for m, v in zip(metas, videos)], []


def normalize_youtube_link(value: str) -> Optional[str]:
    """Accept a youtu.be / watch / shorts / studio URL or a bare ID; return https://youtu.be/ID."""
    value = value.strip()
    if YT_ID_RE.match(value):
        return f"https://youtu.be/{value}"
    patterns = [r"youtu\.be/([A-Za-z0-9_-]{11})", r"[?&]v=([A-Za-z0-9_-]{11})",
                r"/(?:shorts|live|embed|video)/([A-Za-z0-9_-]{11})"]
    for p in patterns:
        m = re.search(p, value)
        if m:
            return f"https://youtu.be/{m.group(1)}"
    return None
