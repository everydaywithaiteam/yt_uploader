"""Derive real chapter timestamps by aligning the final-edit .srt with the script.

The production script supplies section boundaries (## Section N – ...). The words the
speaker actually said come from the .srt. A global, order-preserving word alignment
(difflib) maps script words to caption words, so ad-libs, skipped paragraphs and cut
sections don't throw the rest off. Each section's chapter starts at the caption time of
its first reliably matched word.

If there is no production script, the teleprompter text (same prose, no headings) is
split into sections using the planned chapter times as proportional word offsets.
"""
import difflib
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .metadata import Chapter

MIN_BLOCK = 4          # matched run length (words) that counts as "really said"
MIN_COVERAGE = 0.15    # fraction of a section's words that must match to keep it
MIN_CHAPTER_SECS = 10  # YouTube rule


@dataclass
class Section:
    title: str
    words: List[str]


@dataclass
class AlignedChapter:
    title: str
    planned: Optional[str]
    seconds: Optional[float]
    coverage: float
    note: str = ""


def tokenize(text: str) -> List[str]:
    text = text.lower().replace("’", "'").replace("‘", "'")
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)


def _spoken_lines(lines: List[str]) -> str:
    """Keep only prose: drop headings, tables and [CUE] lines."""
    keep = [l for l in lines if l.strip() and not l.lstrip().startswith(("#", "|", "[", ">"))]
    return " ".join(keep)


def sections_from_script(path: str) -> List[Section]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    sections, title, buf = [], None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if title and tokenize(_spoken_lines(buf)):
                sections.append(Section(title, tokenize(_spoken_lines(buf))))
            name = m.group(1)
            title = name if re.match(r"section\s+\d+", name, re.I) else None
            buf = []
        elif title:
            buf.append(line)
    if title and tokenize(_spoken_lines(buf)):
        sections.append(Section(title, tokenize(_spoken_lines(buf))))
    return sections


def sections_from_prompter(path: str, planned: List[Chapter]) -> List[Section]:
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    # Word offsets where a paragraph follows a [CUE] line: sections always start at one.
    words, cue_starts, after_cue = [], [], False
    for line in lines:
        if line.lstrip().startswith("["):
            after_cue = True
        elif line.strip():
            if after_cue:
                cue_starts.append(len(words))
                after_cue = False
            words += tokenize(line)
    if len(planned) < 2 or not words:
        return [Section("Full script", words)] if words else []
    # Assume the plan was written at a constant speaking rate; extend the last chapter
    # by the average chapter length to estimate the planned end, then snap each
    # estimated cut to the nearest unused cue boundary.
    starts = [c.seconds for c in planned]
    end = starts[-1] + (starts[-1] - starts[0]) / (len(starts) - 1)
    cuts, prev = [], -1
    for s in starts:
        guess = len(words) * s / end
        options = [b for b in cue_starts if b > prev] or [max(prev + 1, round(guess))]
        prev = min(options, key=lambda b: abs(b - guess))
        cuts.append(prev)
    cuts[0] = 0
    cuts.append(len(words))
    return [Section(c.title, words[a:b]) for c, a, b in zip(planned, cuts, cuts[1:])]


def _srt_time(t: str) -> float:
    h, m, rest = t.strip().split(":")
    s, ms = rest.replace(".", ",").split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def srt_words(path: str) -> List[Tuple[str, float]]:
    """Return (word, start_seconds) with times interpolated across each cue."""
    with open(path, encoding="utf-8-sig") as f:
        blocks = re.split(r"\n\s*\n", f.read().replace("\r\n", "\n"))
    out = []
    for block in blocks:
        lines = block.strip().splitlines()
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        start, end = (_srt_time(x) for x in lines[idx].split("-->"))
        words = tokenize(" ".join(lines[idx + 1:]))
        for k, w in enumerate(words):
            out.append((w, start + (end - start) * k / max(1, len(words))))
    return out


def align(sections: List[Section], captions: List[Tuple[str, float]],
          planned: List[Chapter]) -> List[AlignedChapter]:
    script = [w for s in sections for w in s.words]
    spoken = [w for w, _ in captions]
    sm = difflib.SequenceMatcher(None, script, spoken, autojunk=False)
    # script index -> caption index, only for runs long enough to trust
    mapping = {}
    for a, b, size in sm.get_matching_blocks():
        if size >= MIN_BLOCK:
            for k in range(size):
                mapping[a + k] = b + k

    use_planned_titles = len(planned) == len(sections)
    result, offset = [], 0
    for i, sec in enumerate(sections):
        idxs = [j for j in range(offset, offset + len(sec.words)) if j in mapping]
        offset += len(sec.words)
        title = planned[i].title if use_planned_titles else re.sub(r"^section\s+\d+\s*[-–—:]\s*", "", sec.title, flags=re.I)
        plan_ts = planned[i].timestamp if use_planned_titles else None
        coverage = len(idxs) / max(1, len(sec.words))
        if not idxs or coverage < MIN_COVERAGE:
            result.append(AlignedChapter(title, plan_ts, None, coverage, "not found in recording, dropped"))
            continue
        result.append(AlignedChapter(title, plan_ts, captions[mapping[idxs[0]]][1], coverage))

    # First kept chapter must sit at 0:00; enforce minimum chapter length.
    kept = [c for c in result if c.seconds is not None]
    if kept:
        kept[0].seconds = 0.0
    last = None
    for c in kept:
        if last is not None and c.seconds - last.seconds < MIN_CHAPTER_SECS:
            c.note = f"only {c.seconds - last.seconds:.0f}s after previous chapter, merged into it"
            c.seconds = None
            continue
        last = c
    return result


def to_chapters(aligned: List[AlignedChapter]) -> List[Chapter]:
    out = []
    for c in aligned:
        if c.seconds is None:
            continue
        s = int(c.seconds)
        ts = f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"
        out.append(Chapter(ts, c.title))
    return out if len(out) >= 3 else []
