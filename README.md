# yt_uploader

Uploads an Everyday With AI long-form video to YouTube straight from its folder:

```
video NN - <slug>/
  fcp_export/<final>.mp4 + <final>.srt      ← video + captions
  yt_production_package_vN/                 ← highest N wins
    upload_metadata_vN.md                   ← title, description, chapters, tags, settings
    thumbnail_01_*.png                      ← first thumbnail is used by default
```

## Daily use

```bash
./upload --dry-run      # preview: newest video folder not yet uploaded
./upload                # upload it (asks y/N once)
```

Other forms:

```bash
./upload 12                                  # pick "video 12 - …"
./upload 12 --publish-at "2026-11-03 09:00"  # schedule (config timezone)
./upload 12 --privacy unlisted
./upload 12 --title 2 --thumbnail 3          # alternate title #2, third thumbnail
./upload 12 --no-captions
./upload 12 --planned-chapters               # keep the metadata's chapter times as written
```

What it does: validates the metadata (title/description limits, chapter rules **against the
real video length**, tag length, leftover author notes like `[confirm …]`), uploads the video
resumably, sets the thumbnail (re-encodes to JPEG if > 2 MB), uploads the `.srt`, adds to a
playlist if one is named, then prints the Studio link and the steps the API can't do (pin a
comment, end screen/cards, thumbnail Test & Compare).

Uploads are recorded in `state/uploads.json`, so the same folder won't be uploaded twice
(override with `--force`). Default visibility is **private** (`config.json`).

## Mapping from upload_metadata_vN.md

| Section | Used as |
| --- | --- |
| `## Recommended title` | title (`--title N` picks from `## Alternate titles`) |
| `## Description` | description body (Markdown → plain text) |
| `## Chapters` | titles only — times are re-derived from the `.srt` (see below) |
| `## Hashtags` | appended at the end |
| `## Tags` | tags |
| `## Upload settings / checklist` | `Category`, `Audience`, `Language`, `Playlist` |
| `## Suggested pinned comment` | printed as a manual step |

## Chapters from the final edit

The chapter times in `upload_metadata_vN.md` come from the plan, but the final edit is
usually shorter. So the uploader re-times them:

1. Splits `production_script_vN.md` into its `## Section N – …` blocks and keeps only the spoken
   prose (no headings, edit-map tables or `[CUE]` lines).
2. Aligns those words to the words in the final `.srt`, keeping their order (`difflib`). Ad-libs,
   skipped sentences and transcription slips ("Cloud" for "Claude") only lower the match rate.
3. Each chapter starts at the caption time of its section's first matched run of 4+ words. The
   first chapter is forced to 0:00, and sections under 15% matched are dropped as cut.
4. Titles come from the metadata's `## Chapters` when the count equals the number of script
   sections, otherwise from the script headings.

The preview prints planned vs. actual time and the match rate per chapter. If there is no
production script, it falls back to `elgato_teleprompter_vN.txt`. That file has no section
markers, so the boundaries are estimated and a warning tells you to check them.

## One-time setup (≈10 min)

YouTube uploads need **OAuth** (signing in as the channel), not an API key.

1. Go to <https://console.cloud.google.com/>, create a project (e.g. `yt-uploader`).
2. **APIs & Services → Library** → enable **YouTube Data API v3**.
3. **Google Auth Platform → Branding / Audience**: user type **External**, fill in app name and
   your email. Under **Audience**, click **Publish app** (status *In production*). Skip
   verification — it's only you. *If you leave it in "Testing", your login expires every 7 days.*
4. **Data Access → Add scopes**: `.../auth/youtube.upload` and `.../auth/youtube.force-ssl`.
5. **Clients → Create client → Desktop app**. Download the JSON and save it as
   `credentials/client_secret.json` in this repo (git-ignored).
6. Run `./upload` once (not dry-run). A browser opens: sign in, choose the
   **Everyday With AI** channel, click through the "Google hasn't verified this app" warning
   (Advanced → Go to …). The script checks you picked channel `UCZPRXIc9hQKbxq8fiL9TQgw`.

### Uploads stuck as private until the API audit

Videos uploaded through a new, unaudited API project are **locked to private** by YouTube.
To lift that, submit the free **YouTube API Services audit / compliance form**
(<https://support.google.com/youtube/contact/yt_api_form>) for the project. Until it's
approved, uploads work but stay private.

### Quota

Default quota is 10,000 units/day. One full upload here ≈ 1,600 (video) + 50 (thumbnail) +
400 (captions) + ~50 (playlist) ≈ **2,100 units → about 4 long videos/day**. Daily Shorts will
need a quota increase (requested through the same audit form).

## Shorts

TBD — `--short` is reserved. Needs a decision on the shorts folder layout and metadata file.
