"""Health-check Phase 1 data sources. Determines full vs degraded mode.

Exit codes:
  0  full mode      — HN + at least one Reddit historical source up
  1  fail           — HN down (HN is required)
  2  degraded mode  — HN up, both Reddit historical sources down
"""

from __future__ import annotations

import os
import sys

import requests


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


def check_praw() -> bool:
    cid = os.environ.get("REDDIT_CLIENT_ID")
    csec = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and csec):
        print("  praw skipped: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET unset")
        return False
    try:
        import praw

        reddit = praw.Reddit(
            client_id=cid,
            client_secret=csec,
            user_agent=os.environ.get("REDDIT_USER_AGENT", "lemon-healthcheck/0.1"),
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
    pp = check_pullpush()
    print(f"  pullpush.io     : {'OK' if pp else 'DOWN'}")
    arc = check_arctic_shift()
    print(f"  arctic_shift    : {'OK' if arc else 'DOWN'}")
    pr = check_praw()
    print(f"  PRAW            : {'OK' if pr else 'DOWN/UNCONFIGURED'}")

    if not hn:
        print("\nFAIL: HN is required. Cannot proceed.")
        return 1
    reddit_ok = pp or arc
    if not reddit_ok:
        print(
            "\nMode: DEGRADED — both Reddit historical sources DOWN.\n"
            "  Phase 1 will fall back to 2k records via HN + PRAW recent only.\n"
            "  Consider waiting and retrying, or proceed with 3-week passive accumulation."
        )
        return 2
    print("\nMode: FULL — required sources reachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
