# seaintel-monitor
Polls the Sea-Intelligence press room from GitHub Actions and emails a Gemini summary of each new release.

- Run tests: `pytest`
- Source: https://sea-intelligence.com/press-room (Joomla). Release URLs `/press-room/<id>-<slug>`, IDs increasing; the listing shows 100 per page, newest first. A hidden RSS feed exists at `/press-room?format=feed&type=rss` but it is ~4 MB (full text, no pubDate), so the HTML listing is used.
- New = ID > `state/state.json` `last_id` (seeded 422 on 27 Nov 2026). Max 5 emails per run. A failed email doesn't advance state.
- Summary: Gemini REST `generateContent`, models from `GEMINI_MODEL` (default `gemini-flash-latest,gemini-flash-lite-latest`); fallback = opening paragraphs.
- Email: Gmail SMTP_SSL with app password (`EMAIL_USER/PASS/TO`), same as ifo-monitor.
- Unreachable page: one warning email after 12 failed runs in a row, one recovery email. Don't work around bot checks.
- Article body parsing is generic (itemprop=articleBody → .item-page → article → body, <p>/<li> of 40+ chars). It hasn't been tested against the live HTML yet; check the first `--test` email.
