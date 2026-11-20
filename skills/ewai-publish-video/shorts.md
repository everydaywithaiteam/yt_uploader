# Publishing a batch of Shorts

Use this when the user wants to publish, post, or upload **Shorts** ("upload the shorts for
video 13", "post the v13 shorts", "upload this one-off short"). The long-form steps in
`SKILL.md` don't apply here.

Everything runs through `./upload … --shorts` in `/Users/sam/Claude/yt_uploader`. It uploads every
Short in the folder **one after another, in file-name order, as private**, then adds each to the
`shorts_playlist` from `config.json` (Road to 100). Audio is uploaded as-is: the shorts are
normalized before they're edited in Gling, so there's no normalize step.

## Folder layout

```
video NN - <slug>/yt_shorts/
  youtube-shorts-package-vN.md     ← highest N wins: ## Short N → ### Title / ### Description / ### Tags
  v13 1 - Short_….mp4              ← top-level videos only; originals/ is ignored
  v13 2 - Short_….mp4
```

Files are matched to `## Short N` by the leading number in the file name (`v13 3 - …` or
`3 Short_…`). If the names have no numbers, files are matched by position, and the counts must
agree. A one-off Short that doesn't belong to a numbered video folder is passed by path (the
folder itself, or its parent that holds `yt_shorts/`).

## Inputs

- **Which shorts:** a video number (`13`), a folder name fragment, or a path. With nothing, the
  script picks the newest video folder whose `yt_shorts/` has Shorts that haven't been uploaded.
- **Long-form link (optional):** always ask, unless the user already said. The dry run shows a
  suggestion: the long-form upload of the same video folder, from `state/uploads.json`. Ask the
  user to confirm it, paste a different link, or say none (one-off Shorts usually have none).
  Pass the answer as `--long-url <URL or ID>` or `--no-link`.
- **Subset (optional):** `--only 2,5` uploads just those short numbers.
- **Schedule (optional):** `--publish-at "YYYY-MM-DD HH:MM"` (config timezone) schedules the first
  Short; each later Short in the batch publishes `--every-days N` after the previous one (default 1).
  Uploads stay private until their time. If the user gives a start date but no time, ask for one.

## Steps

1. **Preview.**
   ```bash
   cd /Users/sam/Claude/yt_uploader && ./upload <N|path> --shorts --dry-run
   ```
   Summarize for the user: the folder and package file, the suggested long-form link, playlist,
   then a compact table of upload order (short number, file, length, title), and every
   `WARNING`/`ERROR`/`ALREADY UPLOADED` line. Don't paste every description, but mention that
   each one ends with "Watch the full video: <link>" when a link is set.

2. **Ask for the long-form link** (see Inputs) and re-run the dry run with `--long-url …` or
   `--no-link` if the answer changes the plan.

3. **Fix what the preview flags, with the user's OK.** Copy problems are edits to the highest
   `youtube-shorts-package-vN.md`. A pairing `ERROR` means the file names and the package don't
   line up: show both lists and let the user decide. Never pass `--force` to get past errors
   unless the user asks.

4. **Confirm, then upload.** Get a clear yes on the summary, then run it in the background:
   ```bash
   cd /Users/sam/Claude/yt_uploader && ./upload <N|path> --shorts --yes --long-url <URL> 2>&1 | tr '\r' '\n' | grep -v '^  video: [0-9]*%$'
   ```
   (or `--no-link` in place of `--long-url`). Each Short is recorded in
   `state/shorts_uploads.json` as soon as it's uploaded. A re-run skips those and continues with
   the rest. If it prints `STOPPED at Short N (YouTube API quota / upload limit reached)`, tell
   the user that the remaining Shorts can be uploaded by re-running the same command later
   (quota resets daily, midnight Pacific).

5. **Report.** List each Short's youtu.be link and Studio link, plus the "Manual steps left"
   exactly as printed. With a link, that includes setting each Short's **Related video** in
   Studio, which the API can't do.

## Other commands

| Need | Command |
| --- | --- |
| Different playlist / none | `--playlist "Name"` / `--no-playlist` |
| Unlisted instead of private | `--privacy unlisted` |
| One a day from a date | `--publish-at "2026-11-29 09:00"` (`--every-days N` to space them out) |
| Upload a Short again | `--force --only N` (only if the user asks for a second copy) |
