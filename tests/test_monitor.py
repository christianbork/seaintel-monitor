import json

import monitor as m

LISTING = """
<html><body>
<div class="item"><a href="/press-room/422-naec-volumes-flat-west-coast-gains-share"><img src="x.png"></a>
<h2><a href="/press-room/422-naec-volumes-flat-west-coast-gains-share">NAEC Volumes Flat; West Coast Gains Share</a></h2>
<span>25 November 2026</span> <a href="/press-room">Press Room</a>
<a href="/press-room/422-naec-volumes-flat-west-coast-gains-share">Continue reading</a></div>
<div class="item"><h2><a href="https://sea-intelligence.com/press-room/421-nawc-import-growth-at-17-6-in-september">NAWC Import Growth at 17.6% in September</a></h2>
<a href="/press-room/421-nawc-import-growth-at-17-6-in-september">Continue reading</a></div>
<a href="/press-room?start=100">Next</a>
</body></html>
"""

ARTICLE = """
<html><body><nav><p>Menu menu menu menu menu menu menu menu menu menu menu</p></nav>
<div class="item-page"><h2 itemprop="headline">NAEC Volumes Flat; West Coast Gains Share</h2>
<time>25 November 2026</time>
<div itemprop="articleBody">
<p>In issue 750 of the Sunshine report we look at North America East Coast volumes in detail.</p>
<p>Short.</p>
<p>Volumes into the East Coast were flat year-on-year while West Coast ports gained share.</p>
</div></div>
<footer><p>Sea-Intelligence ApS, Copenhagen, Denmark, company address and more text here</p></footer>
</body></html>
"""


class FakeResp:
    def __init__(self, text="", status=200, data=None):
        self.text, self.status_code, self._data = text, status, data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise m.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, pages, gemini=None):
        self.pages, self.gemini, self.posts = pages, gemini, []

    def get(self, url, timeout=None):
        if url in self.pages:
            return FakeResp(self.pages[url])
        return FakeResp("", 404)

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append(url)
        if self.gemini is None:
            return FakeResp("", 429)
        return FakeResp(data={"candidates": [{"content": {"parts": [{"text": self.gemini}]}}]})


URL422 = "https://sea-intelligence.com/press-room/422-naec-volumes-flat-west-coast-gains-share"


def test_parse_listing():
    items = m.parse_listing(LISTING)
    assert [x["id"] for x in items] == [422, 421]
    assert items[0]["title"] == "NAEC Volumes Flat; West Coast Gains Share"
    assert items[0]["url"] == URL422
    assert items[1]["title"] == "NAWC Import Growth at 17.6% in September"


def test_parse_article():
    a = m.parse_article(ARTICLE)
    assert a["title"] == "NAEC Volumes Flat; West Coast Gains Share"
    assert a["date"] == "25 November 2026"
    assert len(a["paragraphs"]) == 2 and "Short." not in a["paragraphs"]
    assert not any("Menu" in p or "Copenhagen" in p for p in a["paragraphs"])


def test_first_run_sets_baseline_without_email(monkeypatch):
    sent = []
    monkeypatch.setattr(m, "send_email", lambda *a, **k: sent.append(a) or True)
    state = {}
    assert m.check(FakeSession({m.PRESS_URL: LISTING}), state, dry_run=False) == 0
    assert state["last_id"] == 422 and not sent


def test_new_release_emailed_once(monkeypatch):
    sent = []
    monkeypatch.setattr(m, "send_email", lambda *a, **k: sent.append(a) or True)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    summary = "- East Coast flat Y/Y.\n- West Coast gains share.\nRead-across: none specific."
    sess = FakeSession({m.PRESS_URL: LISTING, URL422: ARTICLE}, gemini=summary)
    state = {"last_id": 421}
    m.check(sess, state, dry_run=False)
    assert state["last_id"] == 422 and len(sent) == 1
    subject, text, body_html = sent[0]
    assert "NAEC Volumes Flat" in subject and "West Coast gains share" in text
    assert "<li>" in body_html and "<b>Read-across:</b>" in body_html
    m.check(sess, state, dry_run=False)          # second run: nothing new
    assert len(sent) == 1


def test_gemini_failure_falls_back_to_paragraphs(monkeypatch):
    sent = []
    monkeypatch.setattr(m, "send_email", lambda *a, **k: sent.append(a) or True)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    sess = FakeSession({m.PRESS_URL: LISTING, URL422: ARTICLE}, gemini=None)
    m.check(sess, {"last_id": 421}, dry_run=False)
    assert len(sess.posts) == len(m.GEMINI_MODELS)       # tried each model
    assert "No AI summary" in sent[0][1]


def test_failed_email_retries_next_run(monkeypatch):
    monkeypatch.setattr(m, "send_email", lambda *a, **k: False)
    state = {"last_id": 421}
    assert m.check(FakeSession({m.PRESS_URL: LISTING, URL422: ARTICLE}), state, dry_run=False) == 1
    assert state["last_id"] == 421


def test_unreachable_alerts_once(monkeypatch):
    sent = []
    monkeypatch.setattr(m, "send_email", lambda *a, **k: sent.append(a) or True)
    state = {}
    for _ in range(m.FAIL_ALERT_AFTER + 3):
        m.check(FakeSession({}), state, dry_run=False)
    assert len(sent) == 1 and "can't read" in sent[0][0]
    state["last_id"] = 422
    m.check(FakeSession({m.PRESS_URL: LISTING}), state, dry_run=False)
    assert len(sent) == 2 and state["failures"] == 0


def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "STATE_FILE", tmp_path / "s.json")
    m.save_state({"last_id": 5})
    assert json.loads((tmp_path / "s.json").read_text()) == {"last_id": 5}
    assert m.load_state() == {"last_id": 5}


def test_second_recipient(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, u, p): pass
        def send_message(self, msg): sent["to"] = msg["To"]

    monkeypatch.setattr(m.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("EMAIL_USER", "a@gmail.com")
    monkeypatch.setenv("EMAIL_PASS", "abcd efgh ijkl mnop")
    monkeypatch.setenv("EMAIL_TO", "b@seb.dk")
    monkeypatch.setenv("EMAIL_TO2", "c@example.com")
    assert m.send_email("s", "t")
    assert sent["to"] == "b@seb.dk, c@example.com"
