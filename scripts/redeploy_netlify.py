#!/usr/bin/env python3
"""Redeploy web/ to Netlify via the file-hash deploy API.

Usage: NETLIFY_AUTH_TOKEN=*** python3 scripts/redeploy_netlify.py
Token source: $NETLIFY_AUTH_TOKEN or .netlify_token file in repo root.
A new personal access token can be created at https://app.netlify.com/user/applications#personal-access-tokens
"""
import hashlib
import json
import os
import sys
import time
import urllib.request

SITE_ID = "32949321-147e-4179-9382-77c794fe10af"
API = "https://api.netlify.com/api/v1"
WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")


def get_token():
    tok = os.environ.get("NETLIFY_AUTH_TOKEN")
    if not tok:
        path = os.path.join(os.path.dirname(__file__), "..", ".netlify_token")
        if os.path.exists(path):
            tok = open(path).read().strip()
    if not tok:
        sys.exit("no Netlify token: set NETLIFY_AUTH_TOKEN or create .netlify_token")
    return tok


def api(method, path, token, payload=None, body=None, headers=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(payload).encode()
    if body is not None:
        req.data = body
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"API {method} {path} -> {e.code}: {e.read().decode()[:300]}")


def main():
    token = get_token()
    files = {}
    for root, _, names in os.walk(WEB_DIR):
        for name in names:
            if name.endswith(".netlify-tmp"):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, WEB_DIR)
            h = hashlib.sha1()
            with open(full, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            files["/" + rel.replace(os.sep, "/")] = h.hexdigest()
    print(f"{len(files)} files, {sum(os.path.getsize(os.path.join(WEB_DIR, p.lstrip('/'))) for p in files)/1e6:.1f} MB")

    deploy = api("POST", f"/sites/{SITE_ID}/deploys", token,
                 {"files": files})
    did = deploy["id"]
    # "required" lists sha256 hashes not present in Netlify's content store
    by_hash = {}
    for path, sha in files.items():
        by_hash.setdefault(sha, []).append(path)
    required = deploy.get("required") or []
    print(f"deploy {did}: {len(required)} hashes to upload")

    for sha in required:
        for path in by_hash.get(sha, []):
            full = os.path.join(WEB_DIR, path.lstrip("/"))
            with open(full, "rb") as f:
                body = f.read()
            api("PUT", f"/deploys/{did}/files{path}?sha={sha}", token, body=body,
                headers={"Content-Type": "application/octet-stream"})
            print(f"  uploaded {path} ({len(body)/1e6:.1f} MB)")

    for _ in range(60):
        d = api("GET", f"/deploys/{did}", token)
        state = d.get("state")
        if state == "ready":
            print("published:", d.get("ssl_url") or d.get("deploy_ssl_url"))
            return
        if state in ("error", "build_failed"):
            sys.exit(f"deploy failed: {state} {d.get('error') or ''}")
        time.sleep(5)
    sys.exit("deploy did not reach ready state in time")


if __name__ == "__main__":
    main()
