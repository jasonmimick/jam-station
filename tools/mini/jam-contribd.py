#!/usr/bin/env python3
"""jam-contribd — the contributor upload daemon (docs/DESIGN-contributor-identity.md).

Replaces the old SSH+rsync+dedicated-account path. A contributor's identity comes
from Tailscale itself: the daemon only listens on the host's tailscale interface,
so reaching it AT ALL means the connection is real; `tailscale whois <peer-ip>`
then says exactly who they are, no password or key involved. That identity is
checked against jam-station's own member list (an internal-only brain endpoint) —
an unrecognized identity gets silence, not an error, same as nothing were listening.

    POST /contribute?folder=<name>
    Content-Type: application/zip
    <raw zip bytes>

A matched contributor's zip is unpacked straight into $INBOX/<folder>/ — the
EXACT shape jam-inbox.sh already watches and imports (no change to that script
at all, only the arrival mechanism changed) — and the upload is recorded in the
`contributions` table via the brain, for the personal-radio "contributed slice."

Stdlib only, like every host daemon here. Runs via launchd (run.jam.contrib.plist).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

PORT = int(os.environ.get("JAM_CONTRIB_PORT", "8518"))
INBOX = os.path.expanduser(os.environ.get("JAM_CONTRIB_INBOX", "~/jam-contrib-inbox"))
BRAIN = os.environ.get("BRAIN_INTERNAL_URL", "http://jam-brain.localhost:8080")
MAX_UPLOAD = 2 * 1024 * 1024 * 1024  # 2 GB — generous; a whole CD-quality album is ~700 MB

# Tailscale's CLI isn't on launchd's PATH (same gotcha as docker, jam-cdd) —
# check the standalone app bundle first, then whatever's on PATH.
_TAILSCALE_CANDIDATES = (
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    "/usr/local/bin/tailscale",
    "/opt/homebrew/bin/tailscale",
)


def _tailscale_bin() -> str | None:
    for p in _TAILSCALE_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def whois(ip: str) -> str | None:
    """The connecting peer's Tailscale login email, or None if it can't be
    determined (tailscaled down, IP not a tailnet peer, etc — fail closed)."""
    ts = _tailscale_bin()
    if not ts:
        print("jam-contribd: no tailscale binary found", flush=True)
        return None
    try:
        out = subprocess.run([ts, "whois", "--json", ip], capture_output=True,
                             text=True, timeout=5, check=True).stdout
        return json.loads(out).get("UserProfile", {}).get("LoginName") or None
    except Exception as e:
        print(f"jam-contribd: whois failed for {ip}: {e}", flush=True)
        return None


def member_for(email: str) -> dict | None:
    """Ask the brain (internal-only endpoint, never crosses the tunnel) whether
    this email belongs to an approved member — directly OR via their
    tailscale_email alias (see member_by_contributor_email in auth.py)."""
    url = f"{BRAIN}/api/internal/member-by-email?email={urllib.parse.quote(email)}"
    req = urllib.request.Request(url, headers={"Host": "jam-brain.localhost:8080"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception as e:
        print(f"jam-contribd: member lookup failed: {e}", flush=True)
        return None


def record_contribution(email: str, slug: str, folder_name: str) -> None:
    url = f"{BRAIN}/api/internal/contribution"
    body = json.dumps({"email": email, "slug": slug, "folder_name": folder_name}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Host": "jam-brain.localhost:8080",
                                          "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        # a failed attribution write must never undo a successful upload — the
        # station still gets made by jam-inbox.sh regardless; this is a nice-to-
        # have record, not the gate.
        print(f"jam-contribd: contribution record failed (upload still succeeded): {e}",
              flush=True)


def slugify(name: str) -> str:
    """MUST match jam-inbox.sh's own slugify() exactly, or attribution silently
    points at the wrong channel."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:48]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"jam-contribd: {self.address_string()} {fmt % args}", flush=True)

    def _silent_reject(self) -> None:
        # No status line, no body — indistinguishable from nothing listening
        # here at all (decided in docs/DESIGN-contributor-identity.md: no
        # information leak about what this port is or why a request failed).
        try:
            self.connection.close()
        except Exception:
            pass

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/contribute":
            return self._silent_reject()

        folder = urllib.parse.parse_qs(parsed.query).get("folder", [""])[0].strip()
        folder = re.sub(r"[^\w .()\[\]#+-]", "", folder)[:80]   # no path traversal, no junk
        if not folder:
            return self._silent_reject()

        peer_ip = self.client_address[0]
        email = whois(peer_ip)
        if not email:
            return self._silent_reject()

        m = member_for(email)
        if not m:
            print(f"jam-contribd: {email} ({peer_ip}) is not an approved member — rejected",
                  flush=True)
            return self._silent_reject()

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_UPLOAD:
            return self._silent_reject()
        zip_bytes = self.rfile.read(length)

        dest = os.path.join(INBOX, folder)
        try:
            os.makedirs(INBOX, exist_ok=True)
            with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
                # zip slip guard — never let a malicious entry escape INBOX
                for info in zf.infolist():
                    target = os.path.normpath(os.path.join(dest, info.filename))
                    if not target.startswith(os.path.normpath(dest) + os.sep) and target != dest:
                        raise ValueError(f"unsafe path in zip: {info.filename}")
                zf.extractall(dest)
        except Exception as e:
            print(f"jam-contribd: unpack failed for {email}'s '{folder}': {e}", flush=True)
            self.send_response(500)
            self.end_headers()
            return

        slug = "inbox-" + slugify(folder)
        record_contribution(m["email"], slug, folder)
        print(f"jam-contribd: accepted '{folder}' from {m['email']} ({m.get('name', '')}) "
              f"via {email} -> {dest}", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        body = json.dumps({"ok": True, "folder": folder}).encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urllib.parse.urlparse(self.path).path == "/health":
            body = json.dumps({"ok": True, "inbox": INBOX,
                               "tailscale": _tailscale_bin() is not None}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._silent_reject()


def tailscale_ip() -> str | None:
    ts = _tailscale_bin()
    if not ts:
        return None
    try:
        out = subprocess.run([ts, "ip", "-4"], capture_output=True, text=True,
                             timeout=5, check=True).stdout.strip()
        return out or None
    except Exception:
        return None


def main() -> None:
    os.makedirs(INBOX, exist_ok=True)
    bind_ip = tailscale_ip()
    if not bind_ip:
        # Fail LOUD and don't fall back to 0.0.0.0 — binding to every interface
        # would defeat the entire security model (this endpoint accepts writes
        # and must be reachable ONLY over the tailnet). launchd's KeepAlive
        # will retry; tailscaled is probably just still starting up.
        raise SystemExit("jam-contribd: could not determine the tailscale IP — "
                         "refusing to bind 0.0.0.0. Is tailscaled running?")
    print(f"jam-contribd: binding {bind_ip}:{PORT} (tailscale-only) — inbox: {INBOX}",
          flush=True)
    srv = ThreadingHTTPServer((bind_ip, PORT), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
