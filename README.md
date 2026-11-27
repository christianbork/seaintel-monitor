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

- every 20 minutes, 06:00–19:00 UTC on weekdays (07:00–20:00 Copenhagen in winter)
- every 3 hours around the clock, for off-hours releases

Each release URL has an increasing ID (`/press-room/422-...`). Any ID above the last
one seen (`state/state.json`) gets one email, and the state is committed back to the
repo. If the page can't be read for 12 checks in a row (about 4 hours), you get one
warning email, plus another once it recovers. That way a silent failure can't pass
for "no news". If sending the email fails, the release is retried on the next run.

GitHub often starts scheduled runs 5–30 minutes late, so expect an email roughly
10–40 minutes after a release goes up.

## Setup (secrets)

Go to repo → Settings → Secrets and variables → Actions → *New repository secret*:

| Secret | Value |
|---|---|
| `EMAIL_USER` | the Gmail address that sends the email |
| `EMAIL_PASS` | a Gmail **app password** for that account (Google Account → Security → App passwords) |
| `EMAIL_TO` | where alerts go (can be the same address) |
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

GitHub Actions on a private repo includes 2,000 free minutes a month. This job uses
about 1,100 (each run rounds up to 1 minute), and it shares that quota with
ifo-monitor. To check more often (e.g. every 5 minutes), make the repo public, where
Actions minutes are free and unlimited. Secrets stay private, and the state file
only holds a release number.
