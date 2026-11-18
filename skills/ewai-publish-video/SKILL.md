---
name: ewai-publish-video
description: Publish a finished Everyday With AI long-form video to YouTube. Normalizes the final export's audio to -14 LUFS with yt_audio_norm, then uploads it with title, description, chapters (from the edit's fcp_export/chapters.md, else re-timed from the script against the .srt), tags, thumbnail and captions from the video's yt_production_package_vN. Use when the user wants to publish, post, or upload a video (e.g. "publish video 13", "upload the latest video", "post the new long one to YouTube"). Also uploads a batch of YouTube Shorts from a video's yt_shorts/ folder (or a one-off Short), in order, as private, optionally linked to the long-form video (e.g. "upload the shorts for video 13").
---

# ewai-publish-video

Everything runs through one command in the uploader repo, `/Users/sam/Claude/yt_uploader/upload`.
In order, it normalizes the audio, uploads the video, then sets the thumbnail, captions and
playlist. This skill is a thin layer over it: preview, confirm, run, report.

Repo docs: `/Users/sam/Claude/yt_uploader/README.md`. Normalizer docs:
`/Users/sam/Claude/audio_normalization/README.md`.

## Inputs

- **Which video:** a number (`13`), a folder name fragment, or nothing. With nothing, the script
  picks the newest `video NN - …` folder under `~/Desktop/Everyday With AI/videos` that has a
  `yt_production_package_vN` and hasn't been uploaded yet.
- **Visibility (optional):** the default is private. `--publish-at "YYYY-MM-DD HH:MM"` schedules
  it (America/Los_Angeles). `--privacy unlisted|public` is also available.
- **Shorts:** a different flow. Read `shorts.md` in this skill's folder and follow it in place
  of the steps below.

Don't ask for anything the script can find itself.

## Steps

1. **Preview.**
   ```bash
   cd /Users/sam/Claude/yt_uploader && ./upload <N> --dry-run
   ```
   Summarize for the user:
   - the folder and the video file that will be uploaded
   - whether the audio will be normalized first (`Audio:` line)
   - title, privacy, thumbnail, captions and playlist
   - the chapter table and its source: `chapters.md (from the edit)` or the production script
   - every `WARNING`/`ERROR` line

   Exit 1 with "Already uploaded as …" means it's a duplicate. Report the existing link and
   stop. Only use `--force` if the user explicitly wants a second copy.

2. **Fix what the preview flags, with the user's OK.** Problems with the copy itself are edits
   to `upload_metadata_vN.md` in the highest package version. Examples: author notes left in
   the description, `[confirm …]` placeholders, titles over 100 characters. Propose the exact
   edit, make it after the user agrees, then re-run the dry run.
   - Errors block the upload. Never pass `--force` to get past them unless the user asks.

   **Chapters.** Sam narrates screen demos in his own words, so the script often doesn't match
   where a section really starts: alignment latches onto a later scripted line or drops the
   section. The fix is `fcp_export/chapters.md`, the edit's record of real section starts (see
   the README). `ewai-edit-video` writes it when it exports.
   - **Source is `chapters.md`:** a dropped chapter or a match under 85% means its anchor isn't
     in the captions as written. Find the line in the `.srt`, copy its first 6–10 words into the
     `Anchor` cell, re-run the dry run.
   - **Source is the script** and any chapter is dropped or under 70%: offer to write
     `chapters.md`. Read the `.srt` next to the script. For each section, find the first caption
     where that section's content begins. When a screen demo opens the section, that's the
     first words of the ad-libbed walkthrough, not the later scripted sentence. Use the titles
     from the metadata's `## Chapters`, in order. Show the table, write it after the user agrees,
     re-run the dry run. YouTube needs at least 3 chapters, the first at 0:00, each 10s or more.
   - Use `--planned-chapters` only if the user asks for the planned times.

   **Captions.** The uploader sends the newest `.srt` beside the video. If it still looks like a
   raw Tella transcript ("Cloud" for Claude, "SKALE", leading spaces, doubled words), offer to
   clean it with the caption rules in `ewai-edit-video` before uploading. Keep any backup copy
   out of `fcp_export/` or give it a non-`.srt` extension, or it may be uploaded instead.

3. **Confirm, then upload.** Uploading is outward-facing, so get a clear yes on the summary
   first. Then run it in the background: normalizing takes about 1.5 minutes per 10 minutes of
   video, plus upload time.
   ```bash
   cd /Users/sam/Claude/yt_uploader && ./upload <N> --yes [--publish-at "…"] 2>&1 | tr '\r' '\n' | grep -v '^  video: [0-9]*%$'
   ```
   - If the normalizer writes a `⚠️ CHECK THIS — <name>.txt` file, the script stops before
     uploading and prints that file. Relay it. Re-run with `--skip-normalize` only if the user
     decides the audio is fine as it is.
   - If the Google login has expired (Testing mode lasts 7 days), the script opens a browser for
     sign-in first. Tell the user to complete it, signing in as `everyday.with.ai.team@gmail.com`
     and picking the Everyday With AI channel.

4. **Report.** Give the youtu.be link, the Studio edit link, and the "Manual steps left" list
   exactly as the script printed it. That list covers the pinned comment text, end screen and
   cards, the playlist if none was set, and a thumbnail Test & Compare. Also remind the user to
   review the auto-uploaded captions for product-name typos before publishing.

## Other commands

| Need | Command |
| --- | --- |
| Normalize audio only, no upload | `./upload <N> --normalize-only` |
| Upload without normalizing | `./upload <N> --skip-normalize` |
| Test the Google login | `./upload --check-auth` |
| Alternate title / thumbnail | `--title 2`, `--thumbnail 3` |
| Skip uploading captions | `--no-captions` |
| Use the metadata's planned chapter times | `--planned-chapters` |

## Known limits

- Uploads from this Google Cloud project may be **locked to private** until YouTube approves
  the API audit (https://support.google.com/youtube/contact/yt_api_form). If Studio won't let
  the user make the video public, that's the cause.
- The API can't pin comments, add end screens or cards, or start a thumbnail Test & Compare.
- Quota: 100 uploads a day (own bucket), plus 10,000 units a day for everything else
  (≈500 per long-form video). Resets at midnight Pacific.
