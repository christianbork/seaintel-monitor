"""Sea-Intelligence press room monitor.

Checks https://sea-intelligence.com/press-room on a schedule (GitHub Actions) and
emails a short summary of every new press release.

Sea-Intelligence has no API, webhook or email alert for the press room, so "new" means
polling. Each release URL carries an increasing numeric ID
(/press-room/422-naec-volumes-flat-...), so a release is new when its ID is above the
highest ID already seen (kept in state/state.json).

The summary comes from Google's Gemini API (free tier) when GEMINI_API_KEY is set,
otherwise the email carries the article's opening paragraphs.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://sea-intelligence.com"
PRESS_URL = f"{BASE}/press-room"
USER_AGENT = "seaintel-monitor/1.0 (personal press-release alert; github.com/christianbork)"

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "state.json"

ID_RE = re.compile(r"/press-room/(\d+)-[A-Za-z0-9-]+")
DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{4})\b")

MAX_ALERTS_PER_RUN = 5          # guards against an email flood if state is ever lost
FAIL_ALERT_AFTER = 36           # consecutive failed runs (~3 h at 5-min checks) before a "can't reach site" email
GEMINI_MODELS = [m.strip() for m in os.environ.get(
    "GEMINI_MODEL", "gemini-flash-latest,gemini-flash-lite-latest").split(",") if m.strip()]
ARTICLE_CHARS = 12000           # article text sent to Gemini


# --------------------------------------------------------------------------- fetch

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def fetch(session, url: str) -> str:
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


# --------------------------------------------------------------------------- parse

def parse_listing(page: str) -> list[dict]:
    """Releases on the press room page as [{id, title, url}], highest ID first."""
    soup = BeautifulSoup(page, "html.parser")
    found: dict[int, dict] = {}
    for a in soup.find_all("a", href=True):
        m = ID_RE.search(a["href"])
        if not m:
            continue
        rid = int(m.group(1))
        url = requests.compat.urljoin(BASE + "/", a["href"].split("#")[0].split("?")[0])
        title = " ".join(a.get_text(" ", strip=True).split())
        in_heading = a.find_parent(["h1", "h2", "h3"]) is not None
        item = found.setdefault(rid, {"id": rid, "title": "", "url": url, "_h": False})
        # Prefer the heading link's text; ignore "Continue reading" and image links.
        if title and title.lower() not in ("continue reading", "read more") and (
                in_heading or (not item["_h"] and len(title) > len(item["title"]))):
            item["title"], item["_h"] = title, in_heading or item["_h"]
    out = sorted(found.values(), key=lambda x: -x["id"])
    for x in out:
        x.pop("_h")
        x["title"] = x["title"] or x["url"].rsplit("/", 1)[-1]
    return out


def parse_article(page: str) -> dict:
    """Title, date and body paragraphs of one press release page."""
    soup = BeautifulSoup(page, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript"]):
        tag.decompose()
    body = (soup.find(attrs={"itemprop": "articleBody"})
            or soup.find(class_=re.compile(r"\b(item-page|article-body|com-content-article)\b"))
            or soup.find("article") or soup.body or soup)
    paras = []
    for p in body.find_all(["p", "li"]):
        t = " ".join(p.get_text(" ", strip=True).split())
        if len(t) >= 40 and t not in paras:
            paras.append(t)
    h = soup.find(attrs={"itemprop": "headline"}) or soup.find(["h1", "h2"])
    title = " ".join(h.get_text(" ", strip=True).split()) if h else ""
    dm = DATE_RE.search(soup.get_text(" ", strip=True))
    return {"title": title, "date": " ".join(dm.groups()) if dm else "", "paragraphs": paras}


# --------------------------------------------------------------------------- summarise

PROMPT = """You are helping an equity research analyst at SEB who covers listed container
shipping, logistics and port companies (e.g. Maersk, Hapag-Lloyd, ZIM, COSCO, Evergreen,
DSV, Kuehne+Nagel, DP World).

Summarise this Sea-Intelligence press release for him. Output plain text only, exactly:
- 2 to 4 bullet lines starting with "- ", each with a key finding and the article's own
  numbers (schedule reliability %, TEU, capacity, volumes, EBIT, dates).
- One final line starting with "Read-across: " naming which listed carriers, forwarders
  or ports it bears on and how, only where the article states it or it follows directly.
  If nothing follows, write "Read-across: none specific."
Rules: use only facts in the text, never invent numbers, no price targets or
recommendations, paraphrase in your own words, no markdown other than the "- " bullets.

Title: {title}
Date: {date}

Article:
{text}
"""


def summarise(session, art: dict) -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if not key or not art["paragraphs"]:
        return None
    prompt = PROMPT.format(title=art["title"], date=art["date"],
                           text="\n\n".join(art["paragraphs"])[:ARTICLE_CHARS])
    payload = {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800}}
    for model in GEMINI_MODELS:
        try:
            r = session.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=payload, timeout=90)
            if r.status_code >= 400:
                try:
                    err = r.json().get("error", {})
                    detail = f"{err.get('status', '')}: {err.get('message', '')}"
                except ValueError:
                    detail = r.text[:200]
                raise RuntimeError(f"HTTP {r.status_code} {detail}")
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                print(f"Summary from {model}.")
                return text
        except Exception as e:  # fall through to the next model, then to no summary
            print(f"Gemini ({model}) failed: {str(e)[:300]}")
    return None


# --------------------------------------------------------------------------- email

def build_email(item: dict, art: dict, summary: str | None, test: bool = False) -> tuple[str, str, str]:
    title = art["title"] or item["title"]
    subject = f"{'[TEST] ' if test else ''}🚢 Sea-Intelligence: {title}"
    if summary:
        core = summary
    elif art["paragraphs"]:
        core = "\n\n".join(art["paragraphs"][:3]) + "\n\n(No AI summary; opening paragraphs shown.)"
    else:
        core = "(Couldn't read the article text; open the link.)"
    date = art["date"] or "date not found"
    text = f"{title}\n{date}\n{item['url']}\n\n{core}\n\n—\nseaintel-monitor\n"

    lines, bullets = [], []
    for ln in core.splitlines():
        s = ln.strip()
        if s.startswith(("- ", "* ", "• ")):
            bullets.append(f"<li>{html.escape(s[2:])}</li>")
            continue
        if bullets:
            lines.append("<ul>" + "".join(bullets) + "</ul>")
            bullets = []
        if s.lower().startswith("read-across:"):
            lines.append(f"<p><b>Read-across:</b>{html.escape(s[len('read-across:'):])}</p>")
        elif s:
            lines.append(f"<p>{html.escape(s)}</p>")
    if bullets:
        lines.append("<ul>" + "".join(bullets) + "</ul>")
    body_html = (
        f"<div style='font-family:Arial,sans-serif;font-size:14px;max-width:640px'>"
        f"<h2 style='margin-bottom:4px'><a href='{html.escape(item['url'])}'>{html.escape(title)}</a></h2>"
        f"<div style='color:#666;margin-bottom:12px'>{html.escape(date)} · Sea-Intelligence press room</div>"
        + "".join(lines) +
        "<p style='color:#999;font-size:12px'>seaintel-monitor · summary by Gemini, check figures against the release</p></div>")
    return subject, text, body_html


def _mask(addr: str) -> str:
    """Shape of an address for logs, e.g. 'ch***@gmail.com', never the full secret."""
    if "@" not in addr:
        return f"<not an email address, {len(addr)} chars>"
    name, domain = addr.split("@", 1)
    return f"{name[:2]}***@{domain}"


def send_email(subject: str, text: str, body_html: str | None = None) -> bool:
    user, password = (os.environ.get(k, "").strip() for k in ("EMAIL_USER", "EMAIL_PASS"))
    password = password.replace(" ", "")      # Gmail app passwords are shown in groups of 4
    recipients = []
    for k in ("EMAIL_TO", "EMAIL_TO2"):       # EMAIL_TO2 is optional
        addr = os.environ.get(k, "").strip()
        if addr and addr not in recipients:
            recipients.append(addr)
    if not (user and password and recipients):
        print("Email not configured (EMAIL_USER / EMAIL_PASS / EMAIL_TO).")
        return False
    print(f"Email from {_mask(user)} to {', '.join(_mask(a) for a in recipients)}, "
          f"app password {len(password)} chars (a Gmail app password is 16).")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, ", ".join(recipients)
    msg.set_content(text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    errors = []
    for port in (465, 587):
        try:
            if port == 465:
                smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60)
            else:
                smtp = smtplib.SMTP("smtp.gmail.com", 587, timeout=60)
                smtp.starttls()
            with smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
            print(f"Email sent (port {port}).")
            return True
        except smtplib.SMTPAuthenticationError as e:
            print(f"Email failed: Gmail rejected the login ({e.smtp_code}). Check EMAIL_USER is the full "
                  "Gmail address and EMAIL_PASS is a 16-character app password for that same account.")
            return False
        except Exception as e:
            errors.append(f"port {port}: {type(e).__name__}: {e}")
    print("Email failed: " + " | ".join(errors))
    return False


# --------------------------------------------------------------------------- state

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- run

def alert_for(session, item: dict, dry_run: bool, test: bool = False) -> bool:
    try:
        art = parse_article(fetch(session, item["url"]))
    except requests.RequestException as e:
        print(f"Couldn't fetch article {item['url']}: {e}")
        art = {"title": item["title"], "date": "", "paragraphs": []}
    subject, text, body_html = build_email(item, art, summarise(session, art), test=test)
    print("\n" + subject + "\n\n" + text)
    if dry_run:
        return True
    return send_email(subject, text, body_html)


def check(session, state: dict, dry_run: bool) -> int:
    try:
        items = parse_listing(fetch(session, PRESS_URL))
        if not items:
            raise ValueError("no press releases found on the page (layout change or bot check?)")
    except Exception as e:
        state["failures"] = state.get("failures", 0) + 1
        print(f"Press room not readable ({state['failures']} in a row): {e}")
        if state["failures"] == FAIL_ALERT_AFTER and not dry_run:
            send_email("⚠️ seaintel-monitor can't read the Sea-Intelligence press room",
                       f"The last {FAIL_ALERT_AFTER} checks failed. Latest error:\n{e}\n\n"
                       f"New releases won't be emailed until this clears. Check {PRESS_URL} "
                       "and the GitHub Actions log.")
        return 1

    if state.get("failures", 0) >= FAIL_ALERT_AFTER and not dry_run:
        send_email("✅ seaintel-monitor can read the press room again",
                   f"Checks are working again after {state['failures']} failures.")
    state["failures"] = 0
    top = items[0]["id"]

    if "last_id" not in state:
        state["last_id"] = top
        print(f"First run: baseline set to release {top} ({items[0]['title']}). No email sent.")
        return 0

    new = sorted((x for x in items if x["id"] > state["last_id"]), key=lambda x: x["id"])
    if not new:
        print(f"No new releases (latest {top}: {items[0]['title']}).")
        return 0
    if len(new) > MAX_ALERTS_PER_RUN:
        print(f"{len(new)} new releases; emailing the latest {MAX_ALERTS_PER_RUN}.")
        new = new[-MAX_ALERTS_PER_RUN:]
    for item in new:
        if not alert_for(session, item, dry_run):
            print("Email failed; release will be retried next run.")
            return 1
        state["last_id"] = item["id"]
        state.setdefault("history", []).append(
            {"id": item["id"], "title": item["title"], "url": item["url"], "emailed": now_iso()})
        state["history"] = state["history"][-50:]
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--test", action="store_true", help="email the latest release now, marked [TEST]")
    ap.add_argument("--dry-run", action="store_true", help="print instead of emailing; don't save state")
    args = ap.parse_args(argv)

    session = make_session()
    if args.test:
        items = parse_listing(fetch(session, PRESS_URL))
        if not items:
            print("No press releases found on the page.")
            return 1
        return 0 if alert_for(session, items[0], args.dry_run, test=True) else 1

    state = load_state()
    rc = check(session, state, args.dry_run)
    if not args.dry_run:
        save_state(state)
    return rc


if __name__ == "__main__":
    sys.exit(main())
