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
    video_path: Optional[str] = None      # the file that gets uploaded
    master_path: Optional[str] = None     # raw export, input to audio normalization
    needs_normalize: bool = False
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


def is_norm_output(path: str) -> bool:
    """Files written by yt_audio_norm: the normalized master or its intermediate."""
    name = os.path.basename(path).lower()
    return "-normalized_audio" in name or "-stage1" in name


def pick_master(candidates: List[str]) -> Optional[str]:
    """The final edit as exported: FCP export folder first, then newest."""
    masters = [p for p in candidates if not is_norm_output(p)]
    if not masters:
        return None
    return max(masters, key=lambda p: ("fcp" in os.path.dirname(p).lower(), os.path.getmtime(p)))


def normalized_for(master: str, candidates: List[str]) -> Optional[str]:
    """Newest normalized output of this master that is not older than it."""
    base = os.path.splitext(os.path.basename(master))[0] + "-normalized_audio"
    outs = [p for p in candidates
            if os.path.dirname(p) == os.path.dirname(master)
            and os.path.basename(p).startswith(base)
            and os.path.getmtime(p) >= os.path.getmtime(master)]
    return max(outs, key=os.path.getmtime) if outs else None


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
    pkg.master_path = pick_master(pkg.video_candidates)
    if pkg.master_path:
        pkg.video_path = normalized_for(pkg.master_path, pkg.video_candidates)
        pkg.needs_normalize = pkg.video_path is None
        pkg.video_path = pkg.video_path or pkg.master_path
    else:
        # Only normalized files present (master deleted or moved): upload the newest.
        normalized = [p for p in pkg.video_candidates if "-normalized_audio" in os.path.basename(p).lower()]
        pkg.video_path = max(normalized, key=os.path.getmtime) if normalized else None

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
