# seaintel-monitor

Emails you a short summary when **Sea-Intelligence** posts a new press release at
https://sea-intelligence.com/press-room. It runs on GitHub Actions, so it needs no PC
or server.

Each email has the title (linked), date, 2–4 bullets with the release's key figures,
and a one-line read-across to listed carriers, forwarders and ports. The summary
comes from Google Gemini's free API tier. Without a Gemini key, or if Gemini fails,
the email shows the article's opening paragraphs instead.

## How it works

Sea-Intelligence has no API, webhook or alert email for the press room, so the job
checks the page:

- every 5 minutes, 06:00–19:00 UTC on weekdays (07:00–20:00 Copenhagen in winter)
- every 30 minutes the rest of the time

Each release URL has an increasing ID (`/press-room/422-...`). Any ID above the last
one seen (`state/state.json`) gets one email, and the state is committed back to the
repo. If the page can't be read for 36 checks in a row (about 3 hours), you get one
warning email, plus another once it recovers. That way a silent failure can't pass
for "no news". If sending the email fails, the release is retried on the next run.

GitHub sometimes starts scheduled runs late or skips some when busy, so expect an
email usually within 5–20 minutes of a release.

## Setup (secrets)

Go to repo → Settings → Secrets and variables → Actions → *New repository secret*:

| Secret | Value |
|---|---|
| `EMAIL_USER` | the Gmail address that sends the email |
| `EMAIL_PASS` | a Gmail **app password** for that account (Google Account → Security → App passwords) |
| `EMAIL_TO` | where alerts go (can be the same address) |
| `EMAIL_TO2` | optional second recipient |
| `GEMINI_API_KEY` | free key from https://aistudio.google.com/apikey (optional, but no summary without it) |

You can reuse the same `EMAIL_*` values as ifo-monitor. The model defaults to
`gemini-flash-latest` and falls back to `gemini-flash-lite-latest`. To change it, set
a `GEMINI_MODEL` secret and add it to the workflow env. Note: on Gemini's free tier,
Google may use prompts to improve its products. That's fine here, because the input
is a public press release.

## Use

- **Test the chain:** Actions → *Sea-Intelligence press room monitor* → *Run
  workflow* → mode `test`. It emails the latest release right away, marked `[TEST]`.
- **Local:** `pip install -r requirements.txt`, then `python monitor.py --test
  --dry-run` (prints the email without sending it) and `pytest`.

## Cost

The repo is public, so GitHub Actions minutes are free and unlimited. Secrets stay
private. The code and `state/state.json` (just a release number) are visible.

GitHub automatically disables scheduled workflows in public repos after 60 days with
no repository activity. The state commit made on each new release counts as activity,
so this shouldn't happen. If it ever does, GitHub emails you, and you re-enable it
under Actions.
