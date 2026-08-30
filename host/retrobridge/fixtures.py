"""Deterministic pages used only by the authenticated RetroBridge QA mode."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

SELF_TEST_ORIGIN = "https://retrobridge.test"


@dataclass(frozen=True)
class FixtureResponse:
    status: int
    content_type: str
    body: bytes
    headers: dict[str, str] | None = None


INDEX_HTML = b"""<!doctype html>
<meta charset="windows-1252">
<title>RetroBridge QA Home</title>
<style>
  body { margin: 0; min-height: 1600px; font: 16px Arial, sans-serif; background: #f2f2f2; }
  #normal { position: absolute; left: 20px; top: 50px; width: 180px; height: 34px; }
  #popup { position: absolute; left: 220px; top: 50px; width: 180px; height: 34px; }
  #scroll { position: absolute; left: 420px; top: 50px; width: 180px; height: 34px; }
  #name { position: absolute; left: 20px; top: 105px; width: 180px; height: 28px; }
  #submit { position: absolute; left: 220px; top: 105px; width: 100px; height: 32px; }
  #download { position: absolute; left: 20px; top: 155px; }
  #result { position: absolute; left: 220px; top: 155px; }
  #confirm { position: absolute; left: 20px; top: 205px; width: 170px; height: 32px; }
  #prompt { position: absolute; left: 220px; top: 205px; width: 170px; height: 32px; }
  #bottom { position: absolute; left: 20px; top: 1520px; }
</style>
<h1 style="font-size:20px;margin:10px 20px">RetroBridge deterministic QA</h1>
<a id="normal" href="/next">Open normal link</a>
<a id="popup" href="/popup" target="_blank">Open popup link</a>
<a id="scroll" href="/scroll">Open scroll fixture</a>
<input id="name" aria-label="Name" autocomplete="off">
<button id="submit">Submit</button>
<a id="download" href="data:application/octet-stream,RetroBridge98%20deterministic%20download%0D%0A"
   download="retrobridge-qa.txt">Download fixture</a>
<strong id="result">Waiting</strong>
<button id="confirm">Open confirm dialog</button>
<button id="prompt">Open prompt dialog</button>
<strong id="bottom">Bottom of QA page</strong>
<script>
document.querySelector('#submit').onclick = () => {
  const value = document.querySelector('#name').value;
  document.querySelector('#result').textContent = 'Typed: ' + value;
  document.title = 'Typed: ' + value;
};
document.querySelector('#confirm').onclick = () => {
  document.querySelector('#result').textContent = confirm('Continue RetroBridge QA?')
    ? 'Confirmed' : 'Cancelled';
};
document.querySelector('#prompt').onclick = () => {
  const value = prompt('RetroBridge QA name?', 'Win98');
  document.querySelector('#result').textContent = value === null ? 'Prompt cancelled' : 'Prompt: ' + value;
};
</script>
"""

NEXT_HTML = b"""<!doctype html>
<meta charset="windows-1252">
<title>RetroBridge QA Next</title>
<body style="font:18px Arial;background:#dff0d8;padding:24px">
<h1 id="passed">Normal link passed</h1>
<a href="/">Back to fixture</a>
</body>
"""

POPUP_HTML = b"""<!doctype html>
<meta charset="windows-1252">
<title>RetroBridge QA Popup</title>
<body style="font:18px Arial;background:#d9edf7;padding:24px">
<h1 id="passed">Popup redirected into this window</h1>
</body>
"""

DIALOG_HTML = b"""<!doctype html>
<meta charset="windows-1252">
<title>RetroBridge QA Dialog</title>
<body style="font:18px Arial;background:#f7f0d8;padding:24px">
<h1>Dialog round trip</h1>
<strong id="result">Waiting for reply</strong>
<script>
setTimeout(() => {
  document.querySelector('#result').textContent = confirm('Continue RetroBridge QA?')
    ? 'Confirmed' : 'Cancelled';
}, 100);
</script>
</body>
"""

PROMPT_HTML = b"""<!doctype html>
<meta charset="windows-1252">
<title>RetroBridge QA Prompt</title>
<body style="font:18px Arial;background:#f7f0d8;padding:24px">
<h1>Prompt round trip</h1>
<strong id="result">Waiting for reply</strong>
<script>
setTimeout(() => {
  const value = prompt('RetroBridge QA name?', 'Win98');
  document.querySelector('#result').textContent = value === null ? 'Prompt cancelled' : 'Prompt: ' + value;
}, 100);
</script>
</body>
"""

SCROLL_HTML = b"""<!doctype html>
<meta charset="windows-1252">
<title>RetroBridge QA Scroll</title>
<style>
  html { overflow-y: scroll; }
  body { margin: 0; min-height: 1600px; font: 18px Arial, sans-serif; background: #f2f2f2; }
  header { padding: 20px; color: white; background: #24527a; }
  footer { position: absolute; top: 1500px; padding: 20px; }
</style>
<header>Top of scrolling fixture</header>
<footer>Bottom of scrolling fixture</footer>
"""


def fixture_for_url(url: str) -> FixtureResponse | None:
    parsed = urlsplit(url)
    if f"{parsed.scheme}://{parsed.netloc}" != SELF_TEST_ORIGIN:
        return None
    path = parsed.path or "/"
    if path == "/":
        return FixtureResponse(200, "text/html; charset=windows-1252", INDEX_HTML)
    if path == "/next":
        return FixtureResponse(200, "text/html; charset=windows-1252", NEXT_HTML)
    if path == "/popup":
        return FixtureResponse(200, "text/html; charset=windows-1252", POPUP_HTML)
    if path == "/dialog":
        return FixtureResponse(200, "text/html; charset=windows-1252", DIALOG_HTML)
    if path == "/prompt":
        return FixtureResponse(200, "text/html; charset=windows-1252", PROMPT_HTML)
    if path == "/scroll":
        return FixtureResponse(200, "text/html; charset=windows-1252", SCROLL_HTML)
    if path == "/download.bin":
        payload = b"RetroBridge98 deterministic download\r\n"
        return FixtureResponse(
            200,
            "application/octet-stream",
            payload,
            {"Content-Disposition": 'attachment; filename="retrobridge-qa.txt"'},
        )
    if path == "/slow":
        return FixtureResponse(200, "text/plain", b"slow fixture")
    return FixtureResponse(404, "text/plain", b"fixture not found")
