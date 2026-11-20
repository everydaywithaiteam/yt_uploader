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
./upload 12 --playlist "Other playlist"      # instead of the default "Road to 100"
./upload 12 --planned-chapters               # keep the metadata's chapter times as written
./upload 12 --normalize-only                 # just normalize the audio
./upload 12 --skip-normalize                 # upload the export as-is
./upload --check-auth                        # test the Google sign-in
```

What it does: normalizes the export's audio to -14 LUFS with
[`yt_audio_norm`](../audio_normalization) (path in `config.json` → `audio_normalizer`; skipped
when a fresh `-normalized_audio` file already exists; stops before uploading if it writes a
`⚠️ CHECK THIS` file), validates the metadata (title/description limits, chapter rules **against the
real video length**, tag length, leftover author notes like `[confirm …]`), uploads the video
resumably, sets the thumbnail (re-encodes to JPEG if > 2 MB), uploads the `.srt`, adds to the
playlist, then prints the Studio link and the steps the API can't do (pin a
comment, end screen/cards, thumbnail Test & Compare).

Uploads are recorded in `state/uploads.json`, so the same folder won't be uploaded twice
(override with `--force`). Default visibility is **private** (`config.json`).

Playlist: every upload goes to **Road to 100** (`default_playlist` in `config.json`). Order of
precedence: `--playlist NAME` > `playlist_overrides` (folder name → playlist) > `default_playlist`
> the metadata's `Playlist` setting. The playlist must already exist on the channel.

## Claude skill

`skills/ewai-publish-video/SKILL.md` wraps this as `/ewai-publish-video`. It's symlinked into
`~/.claude/skills/`, so edits here are live:

```bash
ln -s "$PWD/skills/ewai-publish-video" ~/.claude/skills/ewai-publish-video
```

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
usually shorter. So the uploader re-times them, using the first source it finds:

1. `--planned-chapters`: the metadata's times as written.
2. **`chapters.md` beside the export** (written by the `ewai-edit-video` skill). Best source: the
   edit knows where each section really starts, including screen demos narrated off-script.
3. Alignment of `production_script_vN.md` against the `.srt` (below).

### chapters.md

```markdown
| Title | Anchor | Edit time |
| --- | --- | --- |
| The finished result | This video is already here in the YouTube Studio | 00:00 |
| Give the uploader a predictable folder | so as you can see, this is my kind of folder structure | 01:26 |
```

`Anchor` is the first few words actually spoken where the chapter starts. The uploader finds each
anchor in the `.srt` (in order, fuzzy, so caption slips still match) and uses that caption's time,
so later trims don't make the file stale. `Edit time` is only shown for comparison. An anchor
that can't be found drops that chapter with a warning. Fix the anchor rather than the time.

### Script alignment (fallback)

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
3. **Google Auth Platform → Get started**: app name, support email, user type **External**.
   Then **Audience → Test users → Add users** and add the Google account that owns the
   channel. (Publishing the app instead needs a home page + privacy policy on a domain you
   own; in Testing mode the login expires every 7 days and the script just reopens the
   browser to sign in again.)
4. *(Optional)* **Data Access → Add scopes**: `youtube.upload` and `youtube.force-ssl`.
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

Uploads (`videos.insert`) have their own bucket: **100 uploads/day**, 1 per call. Everything else
shares **10,000 units/day**: thumbnail 50, captions 400, playlist add 50, lookups 1. So one
long-form video is 1 upload + ≈500 units, and a batch of 7 Shorts is 7 uploads + ≈360 units.
Both reset at midnight Pacific. Source:
<https://developers.google.com/youtube/v3/determine_quota_cost>.

## Shorts

Uploads a batch of Shorts from a video's `yt_shorts/` folder, one after another, as private:

```
video NN - <slug>/yt_shorts/
  youtube-shorts-package-vN.md     ← highest N wins
  v13 1 - Short_….mp4              ← top-level .mp4/.mov only (originals/ ignored)
  v13 2 - Short_….mp4
```

```bash
./upload 13 --shorts --dry-run                  # plan: order, titles, tags, descriptions
./upload 13 --shorts                            # asks for the long-form link, then y/N
./upload 13 --shorts --long-url sXwF7qQpIOY     # link (URL or ID) without the prompt
./upload 13 --shorts --no-link                  # no long-form link
./upload "/path/to/one-off/yt_shorts" --shorts  # a one-off Short outside a video folder
./upload 13 --shorts --only 2,5                 # just Shorts 2 and 5
./upload 13 --shorts --publish-at "2026-11-29 09:00"   # schedule: one a day from then (private until each goes public)
./upload 13 --shorts --publish-at "…" --every-days 2  # every other day
```

- **Metadata:** each `## Short N` section's `### Title`, `### Description` (or
  `### Short description`) and `### Tags`. Script and on-screen sections are ignored.
- **Order and pairing:** files are uploaded in file-name order (natural sort, so 10 comes after 9).
  The leading number in the name (`v13 3 - …`, `3 Short_…`) picks the `## Short N` entry. Names
  without numbers are paired by position, and then the counts must match.
- **Long-form link:** defaults to the long-form upload of the same video folder recorded in
  `state/uploads.json`. With a link, each description ends with `Watch the full video: <link>`,
  and the report reminds you to set the Short's **Related video** in Studio (not in the API).
- **Audio:** uploaded as-is. Shorts are normalized before the Gling edit.
- **Playlist:** `shorts_playlist` in `config.json` (Road to 100); `--playlist NAME` / `--no-playlist`.
- **State:** each Short is recorded in `state/shorts_uploads.json` right after it uploads. A
  re-run skips those (`--force` to upload again). Long-form state isn't touched.
- **Quota:** each Short is 1 of the 100 daily uploads plus 50 units for the playlist (see
  Quota above). If a limit is hit mid-batch, the script stops cleanly and lists what's left. Re-run the same
  command the next day.
