"""Health-check Phase 1 data sources. Determines full vs degraded mode.

Required:
  - HN Algolia
  - Reddit unauth /new.json (with project User-Agent)
  - At least one of: pullpush.io, arctic_shift

Informational:
  - PRAW (only if REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET are set in env;
    enables richer recent-scraping with comments. Without it, the project
    runs fine via the unauth path.)

Exit codes:
  0  full mode      — all required sources up
  1  fail           — HN or Reddit-unauth down
  2  degraded mode  — HN+unauth up, both historical sources down
"""

from __future__ import annotations

import os
import sys

import requests

UA = "lemon-corpus-builder/0.1 (+https://github.com/mobetter20/lemon)"


def check_hn() -> bool:
    try:
        r = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": "Claude", "tags": "story", "hitsPerPage": 1},
            timeout=15,
        )
        return r.status_code == 200 and isinstance(r.json().get("hits"), list)
    except Exception as e:
        print(f"  hn error: {e}")
        return False


def check_reddit_unauth() -> bool:
    """Probe with project User-Agent — Reddit blocks default `python-requests/*`.

    Hits old.reddit.com (matches the host in scrapers/reddit_recent.py) so the
    healthcheck is predictive of the actual run.
    """
    try:
        r = requests.get(
            "https://old.reddit.com/r/ClaudeAI/new.json",
            params={"limit": 1},
            headers={"User-Agent": UA},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  reddit-unauth: HTTP {r.status_code}")
            return False
        body = r.json()
        return isinstance(body.get("data", {}).get("children"), list)
    except Exception as e:
        print(f"  reddit-unauth error: {e}")
        return False


def check_pullpush() -> bool:
    try:
        r = requests.get(
            "https://api.pullpush.io/reddit/search/submission/",
            params={"subreddit": "ClaudeAI", "size": 1},
            timeout=20,
        )
        return r.status_code == 200 and "data" in r.json()
    except Exception as e:
        print(f"  pullpush error: {e}")
        return False


def check_arctic_shift() -> bool:
    try:
        r = requests.get(
            "https://arctic-shift.photon-reddit.com/api/posts/search",
            params={"subreddit": "ClaudeAI", "limit": 1},
            timeout=20,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"  arctic_shift error: {e}")
        return False


def check_praw() -> bool | None:
    """Returns True/False if configured, None if not configured (skipped)."""
    cid = os.environ.get("REDDIT_CLIENT_ID")
    csec = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and csec):
        return None
    try:
        import praw

        reddit = praw.Reddit(
            client_id=cid,
            client_secret=csec,
            user_agent=os.environ.get("REDDIT_USER_AGENT", UA),
        )
        next(iter(reddit.subreddit("ClaudeAI").hot(limit=1)))
        return True
    except Exception as e:
        print(f"  praw error: {e}")
        return False


def main() -> int:
    print("Health-check Phase 1 data sources:")

    hn = check_hn()
    print(f"  HN Algolia      : {'OK' if hn else 'DOWN'}")

    ru = check_reddit_unauth()
    print(f"  reddit /new.json : {'OK' if ru else 'DOWN'}")

    pp = check_pullpush()
    print(f"  pullpush.io     : {'OK' if pp else 'DOWN'}")

    arc = check_arctic_shift()
    print(f"  arctic_shift    : {'OK' if arc else 'DOWN'}")

    pr = check_praw()
    if pr is None:
        print("  PRAW            : UNCONFIGURED (informational; not required)")
    else:
        # Note: PRAW AUTH-FAILED does NOT change the healthcheck exit code.
        # The actual scraper raises at runtime if PRAW creds are set but auth
        # fails — that's where the hard-fail lives. Healthcheck just surfaces
        # the issue early.
        print(f"  PRAW            : {'OK' if pr else 'AUTH-FAILED (will hard-fail at runtime)'}")

    # Required: HN + Reddit-unauth
    if not hn:
        print("\nFAIL: HN is required. Cannot proceed.")
        return 1
    if not ru:
        print("\nFAIL: Reddit unauth /new.json is required. Cannot proceed.")
        print("       (If Reddit is blocking your IP, try a different network.)")
        return 1

    # Historical: at least one of pullpush / arctic_shift
    historical_ok = pp or arc
    if not historical_ok:
        print(
            "\nMode: DEGRADED — both Reddit historical sources DOWN.\n"
            "  Phase 1 will fall back to HN + reddit-recent (~24-48h) only.\n"
            "  Historical reddit voice will be missing from the corpus."
        )
        return 2
    print("\nMode: FULL — required sources reachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
