# seaintel-monitor
Polls the Sea-Intelligence press room from GitHub Actions and emails a Gemini summary of each new release.

- Run tests: `pytest`
- Public repo (free Actions minutes): cron every 5 min 06-19 UTC weekdays, every 30 min otherwise. Public repos have scheduled workflows auto-disabled after 60 days without repo activity; state commits on each new release keep it alive.
- Source: https://sea-intelligence.com/press-room (Joomla). Release URLs `/press-room/<id>-<slug>`, IDs increasing; the listing shows 100 per page, newest first. A hidden RSS feed exists at `/press-room?format=feed&type=rss` but it is ~4 MB (full text, no pubDate), so the HTML listing is used.
- New = ID > `state/state.json` `last_id` (seeded 422 on 27 Nov 2026). Max 5 emails per run. A failed email doesn't advance state.
- Summary: Gemini REST `generateContent`, models from `GEMINI_MODEL` (default `gemini-flash-latest,gemini-flash-lite-latest`); fallback = opening paragraphs.
- Email: Gmail SMTP_SSL 465 (587 STARTTLS fallback) with app password (`EMAIL_USER/PASS/TO`). Logs show masked addresses and password length for debugging. First test email sent 27 Nov 2026.
- Unreachable page: one warning email after 36 failed runs (~3 h) in a row, one recovery email. Don't work around bot checks.
- Article body parsing is generic (itemprop=articleBody → .item-page → article → body, <p>/<li> of 40+ chars). Verified on the live site 27 Nov 2026: GitHub runners can read the site (no bot check), and body extraction works.
