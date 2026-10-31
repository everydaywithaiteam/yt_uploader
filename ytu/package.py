"""Locate a video folder's production package and media files."""
import glob
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

VIDEO_EXTS = (".mp4", ".mov", ".m4v")
# Folders that hold b-roll / raw recordings, never the final edit.
SKIP_DIRS = ("yt_video_vizualizations", "yt_video_visualizations", "screen_studio_recording",
             "yt_shorts", "yt_production_package", "production-package")


@dataclass
class Package:
    video_dir: str
    package_dir: str
    version: int
    metadata_path: str
    video_path: Optional[str] = None
    video_candidates: List[str] = field(default_factory=list)
    captions_path: Optional[str] = None
    script_path: Optional[str] = None
    prompter_path: Optional[str] = None
    thumbnails: List[str] = field(default_factory=list)


def video_number(name: str) -> Optional[int]:
    m = re.match(r"^video\s+(\d+)\b", name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def list_video_dirs(root: str) -> List[str]:
    dirs = [d for d in os.listdir(root)
            if os.path.isdir(os.path.join(root, d)) and video_number(d) is not None]
    return [os.path.join(root, d) for d in sorted(dirs, key=video_number)]


def latest_versioned(parent: str, prefix: str):
    """Return (path, N) for the highest prefix_vN entry in parent."""
    best = None
    for entry in os.listdir(parent):
        m = re.match(rf"^{re.escape(prefix)}_v(\d+)(\.\w+)?$", entry)
        if m and (best is None or int(m.group(1)) > best[1]):
            best = (os.path.join(parent, entry), int(m.group(1)))
    return best


def find_videos(video_dir: str) -> List[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(video_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(SKIP_DIRS) and not d.startswith(".")]
        found += [os.path.join(dirpath, f) for f in filenames if f.lower().endswith(VIDEO_EXTS)]
    return found


def pick_video(candidates: List[str]) -> Optional[str]:
    if not candidates:
        return None
    # Prefer the FCP export folder, then normalized-audio renders, then newest.
    def score(p):
        return ("fcp" in os.path.dirname(p).lower(),
                "normalized_audio" in os.path.basename(p).lower(),
                os.path.getmtime(p))
    return max(candidates, key=score)


def load(video_dir: str) -> Package:
    video_dir = os.path.abspath(video_dir)
    found = latest_versioned(video_dir, "yt_production_package")
    if not found:
        raise FileNotFoundError(f"No yt_production_package_vN folder in {video_dir}")
    package_dir, version = found
    meta = latest_versioned(package_dir, "upload_metadata")
    if not meta:
        raise FileNotFoundError(f"No upload_metadata_vN.md in {package_dir}")

    pkg = Package(video_dir=video_dir, package_dir=package_dir, version=version, metadata_path=meta[0])
    pkg.video_candidates = find_videos(video_dir)
    pkg.video_path = pick_video(pkg.video_candidates)

    if pkg.video_path:
        srts = glob.glob(os.path.join(os.path.dirname(pkg.video_path), "*.srt"))
        if srts:
            pkg.captions_path = max(srts, key=os.path.getmtime)

    script = latest_versioned(package_dir, "production_script")
    pkg.script_path = script[0] if script else None
    prompter = latest_versioned(package_dir, "elgato_teleprompter")
    pkg.prompter_path = prompter[0] if prompter else None

    pkg.thumbnails = sorted(
        p for p in glob.glob(os.path.join(package_dir, "thumbnail*"))
        if p.lower().endswith((".png", ".jpg", ".jpeg"))
    )
    return pkg
