# Reel Studio

A local desktop app for pulling Instagram reel and profile data in bulk, with a data viewer
and one-click exports. It looks and behaves like a small Apify, but it runs on your own
machine, on your own Instagram session, with no per-run cost.

Measured on a normal laptop: **100 reels in about 1.3 minutes**, including profile
enrichment. No API keys, no proxy bills, no cloud.

```
  20 reels + owner follow counts   ->  16.1 s   (0.80 s per reel, 6 workers)
  100 reels, projected             ->  ~1.3 min
```

---

## What it does

- **Reels**: paste any number of reel URLs or shortcodes. Each row returns likes, comments,
  reposts, caption, owner, location, posting date, duration, and the **music title and artist**
  (licensed track or original audio).
- **Auto enrichment**: the owner's follower count is fetched once per account, automatically.
  If 100 reels come from 20 accounts, that is 20 extra requests, not 100.
- **Profiles**: paste profile URLs or handles and get followers, following, post count, full
  name and bio.
- **Data viewer**: a mini spreadsheet in the browser. Sort by any column, filter across every
  field, choose which columns you see, follow links straight to the post or profile.
- **Exports**: CSV, XLSX (real Excel file, no extra libraries needed) and JSON.
- **Run history**: every run is kept on disk and can be reopened after a restart.
- **Two engines**: a fast parallel one and a slower self-healing one, switchable per run.
- **Light and dark theme**, keyboard shortcuts, no build step, no dependencies to install
  beyond Python itself.

---

## Requirements

| What | Why | Notes |
|---|---|---|
| **Python 3.9+** | runs the app | standard library only, nothing to `pip install` |
| **Node 22.13+** | runs `api-anything` | only needed to learn and refresh the Instagram session |
| **Google Chrome** | signs in to Instagram once, and learns the capture | any recent version |
| **An Instagram account** | the pages are gated | you sign in yourself, the app never sees your password |
| **api-anything** | the engine that learns and drives the site | free, open source, MIT |

Windows, macOS and Linux all work. On Windows you also get a Desktop shortcut and a
chromeless app window, so it feels like a normal desktop program.

---

## Install

### 1. Get Python

Check it:

```bash
python --version      # or python3 --version
```

Anything 3.9 or newer is fine. There is nothing to pip install.

### 2. Get api-anything

```bash
git clone --depth 1 https://github.com/goodnight000/api-anything.git
cd api-anything
npm ci
npm install -g "$(npm pack --silent)"
```

`npm pack` first on purpose: a plain `npm install -g github:...` breaks on npm 11 because it
skips build dependencies.

Check it:

```bash
api-anything sites
api-anything call hacker-news search query=sqlite
```

### 3. Download Reel Studio

```bash
git clone https://github.com/ilovekushgola/reel-studio.git
cd reel-studio
```

Or download the ZIP from GitHub and unzip it anywhere.

### 4. Sign in to Instagram (once)

```bash
api-anything login instagram --window
```

A Chrome window opens. Sign in, clear any 2FA or captcha, then **close the window**. The
session is stored by api-anything and reused from then on. Your password never goes through
Reel Studio.

### 5. Learn the two operations (once)

```bash
python setup_ops.py
```

This teaches api-anything the two operations the app drives, then verifies both with live
calls. It uses Chrome twice, so give it a minute.

```
Reel Studio :: operation setup
----------------------------------
  ok    api-anything found
  ok    Instagram session present
  ..    learning getReel (runs Chrome twice, give it a moment)
  ok    getReel learned
  ..    learning getProfile (runs Chrome twice, give it a moment)
  ok    getProfile learned

verifying with live calls
----------------------------------
  ok    getReel answered, tier 1  {'username': 'theakshattongia', 'like_count': 880}
  ok    getProfile answered, tier 1  {'username': 'nasa', 'followers_display': '104M'}
----------------------------------
Setup complete.
```

Re-run it with `--verify` to check things later.

### 6. Run it

**Windows, the easy way**

```bash
python make_icon.py
powershell -NoProfile -ExecutionPolicy Bypass -File make_shortcut.ps1
```

That puts **Reel Studio** on your Desktop and in the Start Menu, with its own icon.
Double-click it from then on: the backend starts silently in the background and a
chromeless app window opens. No terminal, no commands.

**Any platform, from a terminal**

```bash
python server.py
```

Then open http://127.0.0.1:8787. Useful flags:

```bash
python server.py --no-browser        # do not auto-open a browser
REEL_STUDIO_PORT=9000 python server.py
```

---

## Using it

### Reels

1. Paste reel links or shortcodes into **Source list**, one per line. All of these work:
   `https://www.instagram.com/reels/ABC123/`, `https://www.instagram.com/reel/ABC123/`,
   `https://www.instagram.com/p/ABC123/`, or just `ABC123`.
2. Or click **Load file** and pick a `.txt` or `.csv`. Every URL in the file is pulled out.
3. Set **Engine** to `Fast, parallel` and pick a **Workers** count (6 to 8 is the sweet spot).
4. Leave **Enrich with owner profile** ticked if you want follower counts per row.
5. **Start scrape**. Progress, ETA and a live log update as it runs. **Stop** ends it cleanly,
   keeping everything collected so far.

### Profiles

Same flow, but the input is profile links or handles: `https://www.instagram.com/nasa/`,
`@nasa`, or `nasa`.

### Data

Pick any run from the dropdown. Click a column header to sort, use the search box to filter
across every field, and **Columns** to choose what you see. **CSV**, **XLSX** and **JSON**
download the current run.

### Settings

- **Session**: shows whether Instagram is reachable. **Refresh session** reopens the sign-in
  window when things start failing with an auth error.
- **Engine**: the same Fast/Safe choice and defaults, saved for new runs.
- **Run history**: every past run, with an Open button and a Delete button.

Keyboard shortcuts: `1` Reels, `2` Profiles, `3` Data, `4` Settings.

---

## The two engines

| | Fast | Safe |
|---|---|---|
| How | reads the pages directly from your machine using the api-anything session cookies, in parallel | drives the `api-anything` CLI, one request at a time |
| Speed | **0.80 s per reel** at 6 workers | about 5.2 s per reel |
| 100 reels | **~1.3 min** | ~8.7 min |
| Self-heals | no | yes, repairs itself when Instagram changes shape |
| Use when | normal bulk runs | after an Instagram change, or if Fast starts failing |

Why Fast is faster, honestly: the CLI spawns a Node process per call and enforces a one
second gap between requests. Neither is required by the website. Fast does the same requests
with the same headers and cookies, minus the overhead, and overlaps them.

If Fast returns errors, switch to Safe. If Safe fails too, refresh the session.

---

## Data you get

**Reel** (per reel)

| Field | Meaning |
|---|---|
| `shortcode` | the reel id, so the URL is `instagram.com/reel/<shortcode>/` |
| `username`, `verified` | who posted it |
| `likes`, `comments`, `reposts` | public counts at the time of the run |
| `date` | posting date, UTC |
| `caption` | full caption text |
| `location` | tagged place, when there is one |
| `duration`, `width`, `height` | video length and resolution |
| `music_title`, `music_artist` | the track used, or the account name for original audio |
| `music_type` | `licensed` for a track, `original` for the creator's own audio |
| `owner_followers`, `owner_followers_display` | the owner's follower count |
| `url` | clickable link to the reel |
| `tier`, `ok`, `error` | transport used, and whether the row succeeded |

**Profile** (per profile)

`username`, `full_name`, `followers`, `followers_display`, `following`, `posts`, `bio`,
`profile_pic`.

**About follower counts**: Instagram shows an exact number below 10k (`29`, `1,670`) and an
abbreviated one at or above 10k (`214K`, `104M`). The exact figure for large accounts is not
in the page, so it is not available here.

**Not available publicly**: plays, reach, impressions, saves and profile visits. Those are
private to the account owner. No tool can read them from someone else's reel.

---

## Project layout

```
reel-studio/
  server.py          HTTP API plus the job runner (standard library only)
  engine.py          rows built from the api-anything CLI operations
  fastfetch.py       the direct HTTP engine that makes bulk runs fast
  xlsx_writer.py     writes real .xlsx files with no dependencies
  setup_ops.py       one time installer for the two Instagram operations
  make_icon.py       generates icon.ico
  make_shortcut.ps1  creates the Windows Desktop and Start Menu shortcuts
  ReelStudio.vbs     Windows launcher: starts the backend, opens the app window
  start.bat          plain Windows launcher for a terminal
  static/
    index.html       the whole UI
    styles.css       design tokens for both themes
    app.js           UI logic, no framework
  jobs/            run history, created at runtime
  exports/         generated files, created at runtime
  settings.json    saved defaults, created at runtime
```

---

## How it works

1. `api-anything` learned two operations by watching Instagram's own page make its requests.
   That produced `~/.api-anything/sites/instagram.json`, which holds the exact HTTP request,
   the headers the site accepts, and a recipe for pulling fields out of the response.
2. `api-anything login instagram` imported your session cookies into
   `~/.api-anything/sessions/instagram.json`.
3. Reel Studio reads those two files. **Safe** mode shells out to the CLI. **Fast** mode sends
   the same request itself, with the recorded headers and your cookies, from a pool of worker
   threads, and parses one reel object per page.
4. Results become rows, rows go to the browser, exports come from the same rows.

Nothing about your session leaves the machine, and there is no server to log in to.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `api-anything: command not found` | step 2 above, then reopen the terminal |
| Setup says no Instagram session | run `api-anything login instagram --window` and close the window after signing in |
| Rows fail with `auth` | session expired. Settings, then **Refresh session**, then run again |
| Rows fail with `rate` | Instagram is throttling. Stop, wait a few minutes, drop Workers to 4 |
| Fast mode returns nothing | Instagram changed the page. Switch to Safe, and re-learn with `python setup_ops.py --force` |
| The Start Menu shortcut opens nothing | run `start.bat` once in the project folder to read the real error |
| Port already in use | `REEL_STUDIO_PORT=9000 python server.py` |
| Excel says the file is corrupt | regenerate it. XLSX export writes a standards-compliant workbook; an interrupted download is the usual cause |

**If Instagram changes something**, `api-anything` is designed to repair itself. Re-learn the
operations with:

```bash
python setup_ops.py --force
```

---

## Limits and fair use

- This is a personal tool. Use it on **your own account** and on public content you are
  allowed to collect, and respect Instagram's terms and any rate limits.
- Follower counts are what the page shows, so large accounts are abbreviated.
- Private metrics such as reach and plays are not accessible for other people's posts.
- Bulk runs hit the same endpoints a browser does, just faster. Keep Workers sane (6 to 8);
  pushing to 12 raises the chance of throttling for no real gain.

---

## Credits

- Engine and Instagram operations: [api-anything](https://github.com/goodnight000/api-anything)
  by goodnight000 (MIT).
- Type: Schibsted Grotesk and JetBrains Mono, served for the local UI.

## License

MIT. See [LICENSE](LICENSE).
