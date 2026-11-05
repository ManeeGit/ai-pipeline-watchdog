"""Operator-invoked, read-only post-deployment HTTP acceptance checks. Never provisions resources."""
import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Refusing to forward an identity token through a redirect")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Verified Cloud Run service URL")
    parser.add_argument("--token-env", default="WATCHDOG_ID_TOKEN")
    parser.add_argument("--expect-mode", choices=["synthetic", "gcs"], default="synthetic")
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".run.app") or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        parser.error("Provide the exact HTTPS Cloud Run service origin, with no credentials, path, or query")
    token = os.environ.get(args.token_env)
    if not token:
        parser.error("Identity token environment variable is missing; obtain one using your approved identity workflow")
    opener = urllib.request.build_opener(NoRedirect())
    def get(path, authenticated):
        request = urllib.request.Request(args.url.rstrip("/") + path,
                    headers={"Authorization": "Bearer " + token} if authenticated else {})
        try:
            with opener.open(request, timeout=30) as response:
                return response.status, response.read(2 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            return exc.code, b""
    unauth, _ = get("/api/summary", False)
    if unauth not in {401, 403}:
        raise RuntimeError("Acceptance failed: unauthenticated metadata access was not rejected")
    status, body = get("/api/summary", True)
    if status != 200:
        raise RuntimeError("Acceptance failed: authorized summary access")
    summary = json.loads(body)
    if summary.get("deployment", {}).get("input_mode") != args.expect_mode:
        raise RuntimeError("Acceptance failed: unexpected input mode")
    ready_status, ready_body = get("/readyz", True)
    if ready_status != 200 or not json.loads(ready_body).get("ready"):
        raise RuntimeError("Acceptance failed: no recent successful scan")
    metrics_status, _ = get("/metrics", True)
    if metrics_status != 200:
        raise RuntimeError("Acceptance failed: metrics endpoint")
    print(json.dumps({"passed": True, "unauthenticated_rejected": True, "authorized_summary": True,
                      "recent_scan": True, "metrics": True, "input_mode": args.expect_mode}))


if __name__ == "__main__":
    main()
