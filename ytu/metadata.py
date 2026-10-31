"""Parse upload_metadata_vN.md into a structured upload plan."""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

CATEGORIES = {
    "film & animation": "1", "autos & vehicles": "2", "music": "10",
    "pets & animals": "15", "sports": "17", "travel & events": "19",
    "gaming": "20", "people & blogs": "22", "comedy": "23",
    "entertainment": "24", "news & politics": "25", "howto & style": "26",
    "education": "27", "science & technology": "28",
    "nonprofits & activism": "29",
}

LANGUAGES = {
    "english": "en", "polish": "pl", "spanish": "es", "german": "de",
    "french": "fr", "italian": "it", "portuguese": "pt",
}

# Text that looks like a note to the author rather than viewer-facing copy.
PLACEHOLDER_PATTERNS = [
    r"\[confirm[^\]]*\]", r"\bTBD\b", r"\bTODO\b", r"\bonly if you intend\b",
    r"\[insert[^\]]*\]", r"\bplaceholder\b", r"<[^>]+>",
]

CHAPTER_RE = re.compile(r"^\s*[-*]?\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—]?\s*(.+?)\s*$")


@dataclass
class Chapter:
    timestamp: str
    title: str

    @property
    def seconds(self) -> int:
        parts = [int(p) for p in self.timestamp.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        h, m, s = parts
        return h * 3600 + m * 60 + s


@dataclass
class UploadMetadata:
    source: str
    title: str = ""
    alt_titles: List[str] = field(default_factory=list)
    description_body: str = ""
    chapters: List[Chapter] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    pinned_comment: str = ""
    settings: Dict[str, str] = field(default_factory=dict)
    category_id: Optional[str] = None
    made_for_kids: Optional[bool] = None
    language: Optional[str] = None
    playlist: Optional[str] = None

    @property
    def description(self) -> str:
        parts = [self.description_body.strip()]
        if self.chapters:
            parts.append("Chapters:\n" + "\n".join(f"{c.timestamp} {c.title}" for c in self.chapters))
        if self.hashtags:
            parts.append(" ".join(self.hashtags))
        return "\n\n".join(p for p in parts if p)


def split_sections(text: str) -> Dict[str, str]:
    sections: Dict[str, List[str]] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1).strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def find_section(sections: Dict[str, str], *needles: str) -> str:
    for needle in needles:
        for name, body in sections.items():
            if needle in name:
                return body
    return ""


def md_to_plain(text: str) -> str:
    """Convert the light Markdown used in descriptions to YouTube plain text."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                      lambda m: m.group(2) if m.group(1) == m.group(2) else f"{m.group(1)}: {m.group(2)}",
                      line)
        line = re.sub(r"(\*\*|__)(.+?)\1", r"\2", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"^\s*[-*]\s+", "• ", line)
        out.append(line.rstrip())
    # collapse 3+ blank lines
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def strip_list_marker(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()


def parse(path: str) -> UploadMetadata:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    sections = split_sections(text)
    meta = UploadMetadata(source=path)

    title_block = find_section(sections, "recommended title", "title")
    meta.title = next((strip_list_marker(l) for l in title_block.splitlines() if l.strip()), "")

    alt = find_section(sections, "alternate title", "alternative title")
    meta.alt_titles = [strip_list_marker(l) for l in alt.splitlines() if l.strip()]

    meta.description_body = md_to_plain(find_section(sections, "description"))

    for line in find_section(sections, "chapter").splitlines():
        m = CHAPTER_RE.match(line)
        if m:
            meta.chapters.append(Chapter(m.group(1), m.group(2)))

    tags_block = find_section(sections, "tags")
    raw_tags = re.split(r"[,\n]", tags_block)
    meta.tags = [strip_list_marker(t).lstrip("#") for t in raw_tags if strip_list_marker(t)]

    meta.hashtags = re.findall(r"#[\w]+", find_section(sections, "hashtag"))

    meta.pinned_comment = md_to_plain(find_section(sections, "pinned comment"))

    for line in find_section(sections, "upload settings", "checklist").splitlines():
        m = re.match(r"^\s*[-*]\s+([^:]+):\s*(.+)$", line)
        if m:
            meta.settings[m.group(1).strip().lower()] = m.group(2).strip()

    cat = meta.settings.get("category", "").lower()
    meta.category_id = CATEGORIES.get(cat)
    audience = meta.settings.get("audience", "").lower()
    if "not made for kids" in audience:
        meta.made_for_kids = False
    elif "made for kids" in audience:
        meta.made_for_kids = True
    meta.language = LANGUAGES.get(meta.settings.get("language", "").lower())
    meta.playlist = meta.settings.get("playlist")
    return meta


def find_placeholders(text: str) -> List[str]:
    hits = []
    for line in text.splitlines():
        if any(re.search(p, line, re.IGNORECASE) for p in PLACEHOLDER_PATTERNS):
            hits.append(line.strip())
    return hits
