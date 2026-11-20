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
  v13 1 - Short_…-export.mp4       ← a Gling export wins over the raw file beside it
  v13 2 - Short_….mp4
```

When a raw recording and its `-export` sit side by side, only the export is uploaded. Don't move
or rename files to get around this.

Files are matched to `## Short N` by the leading number in the file name (`v13 3 - …` or
`3 Short_…`). If the names have no numbers, files are matched by position, and the counts must
agree. A one-off Short that doesn't belong to a numbered video folder is passed by path (the
folder itself, or its parent that holds `yt_shorts/`).

## Inputs

- **Which shorts:** a video number (`13`), a folder name fragment, or a path. With nothing, the
  script picks the newest video folder whose `yt_shorts/` has Shorts that haven't been uploaded.
- **Long-form link:** link the Shorts to the main video without asking. Use, in order: a link the
  user gave; the `Long-form:` suggestion in the dry run (the same folder's upload in
  `state/uploads.json`); a `youtu.be/` or `watch?v=` link in the video folder's
  `yt_production_package_vN` files. Pass it as `--long-url <URL or ID>`. Only if none of these
  turns one up, ask the user for the link or whether to go without (`--no-link`).
- **Subset (optional):** `--only 2,5` uploads just those short numbers.
- **Schedule (optional):** `--publish-at YYYY-MM-DD` schedules the first Short at the config's
  `default_publish_time` (8:45 AM Pacific); each later Short publishes `--every-days N` after the
  previous one (default 1, one a day). Uploads stay private until their slot, so "schedule them,
  keep them private" means exactly this. Pass a time (`"YYYY-MM-DD HH:MM"`) only when the user
  names one. Don't ask for a time.

## Steps

1. **Preview.**
   ```bash
   cd /Users/sam/Claude/yt_uploader && ./upload <N|path> --shorts --dry-run
   ```
   Include the `--long-url` and `--publish-at` you'll use. Check every
   `WARNING`/`ERROR`/`ALREADY UPLOADED` line; already-uploaded Shorts are skipped on their own.

2. **Stop only for real problems.** A pairing `ERROR` (file names and package don't line up), an
   `ERROR` in the copy, or no long-form link found: tell the user and wait. Copy fixes are edits to
   the highest `youtube-shorts-package-vN.md`, made with the user's OK. Never pass `--force` to get
   past errors unless the user asks. `WARNING`s alone don't block.

3. **Upload without asking.** Running the skill is the go-ahead, so don't ask for a confirmation.
   Run it in the background:
   ```bash
   cd /Users/sam/Claude/yt_uploader && ./upload <N|path> --shorts --yes --long-url <URL> [--publish-at YYYY-MM-DD] 2>&1 | tr '\r' '\n' | grep -v '^  video: [0-9]*%$'
   ```
   (or `--no-link` in place of `--long-url`). Each Short is recorded in
   `state/shorts_uploads.json` as soon as it's uploaded. A re-run skips those and continues with
   the rest. If it prints `STOPPED at Short N (YouTube API quota / upload limit reached)`, tell
   the user that the remaining Shorts can be uploaded by re-running the same command later
   (quota resets daily, midnight Pacific).

4. **Report.** List each Short with its publish date, title, youtu.be link and Studio link, plus
   the "Manual steps left" exactly as printed. With a link, that includes setting each Short's **Related video** in
   Studio, which the API can't do.

## Other commands

| Need | Command |
| --- | --- |
| Different playlist / none | `--playlist "Name"` / `--no-playlist` |
| Unlisted instead of private | `--privacy unlisted` |
| One a day from a date | `--publish-at 2026-11-29` (8:45 AM; `--every-days N` to space them out) |
| Upload a Short again | `--force --only N` (only if the user asks for a second copy) |
