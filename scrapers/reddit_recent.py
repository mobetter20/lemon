"""Reddit recent scraper.

Two paths, picked at runtime:

- **unauth** (default): hits Reddit's public JSON endpoints (/r/<sub>/new.json).
  No credentials needed. Fetches the latest 100 posts per subreddit. Comments
  are NOT fetched here — arctic_shift / pullpush handle comments for older
  posts, and the /comments/<id>/.json endpoint returns "more" sentinels that
  require extra fetches and would explode our request volume. The unauth
  scraper exists to plug the ~24-48h freshness gap that historical sources
  lag behind.

- **praw** (opt-in): used iff REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET are in
  env. Pulls posts AND comments. On auth failure HARD-FAILS rather than
  silently falling back to unauth — silent fallback masks misconfigured
  credentials.

Same `Record` schema as the rest of the pipeline. Same parent-model
inheritance for comments (PRAW path only).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .common import (
    DedupIndex,
    Record,
    detect_model,
    detect_release_event,
    load_model_keywords,
    load_releases,
    utc_iso_from_unix,
    write_record,
)

UA = "lemon-corpus-builder/0.1 (+https://github.com/mobetter20/lemon)"
SLEEP_SECONDS = 1.5

# old.reddit.com is more lenient with bot traffic than www.reddit.com.
# Same JSON shape on both. Tested against r/ClaudeAI/new.json.
REDDIT_HOST = "https://old.reddit.com"


def _has_praw_creds() -> bool:
    """True iff both env vars are set AND non-empty after strip.

    GH Actions secrets sometimes appear as `""` when undefined; that should
    fall through to the unauth path, not trigger the PRAW path with empty creds.
    """
    cid = (os.environ.get("REDDIT_CLIENT_ID") or "").strip()
    csec = (os.environ.get("REDDIT_CLIENT_SECRET") or "").strip()
    return bool(cid and csec)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def _get_json(url: str, params: dict | None = None, timeout: int = 30) -> dict:
    resp = requests.get(
        url, params=params or {}, headers={"User-Agent": UA}, timeout=timeout
    )
    # 429/403 = rate limit / blocked. tenacity will retry.
    if resp.status_code in (429, 403):
        raise requests.HTTPError(f"HTTP {resp.status_code} from {url}")
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Unauth path — public /r/<sub>/new.json, posts only
# ---------------------------------------------------------------------------

def _scrape_via_unauth(
    corpus_dir: Path,
    config_dir: Path,
    dedup: DedupIndex | None,
) -> int:
    with open(config_dir / "subreddits.json") as f:
        cfg = json.load(f)
    subs: list[str] = cfg["subreddits"]
    floor: int = cfg["selection_strategy"].get("min_score_floor", 5)

    keywords = load_model_keywords(config_dir)
    releases = load_releases(config_dir)

    n_records = 0
    n_subs_succeeded = 0  # for the all-subs-failed guard
    for sub in subs:
        print(f"[reddit_recent_unauth] r/{sub}", flush=True)
        try:
            data = _get_json(
                f"{REDDIT_HOST}/r/{sub}/new.json", params={"limit": 100}
            )
        except Exception as e:
            print(f"  fetch failed: {e}")
            time.sleep(SLEEP_SECONDS)
            continue
        n_subs_succeeded += 1

        children = data.get("data", {}).get("children", []) or []
        kept = 0
        for child in children:
            if child.get("kind") != "t3":
                continue
            p = child.get("data") or {}

            score = int(p.get("score") or 0)
            if score < floor:
                continue
            pid = p.get("id") or ""
            if not pid:
                continue

            permalink_path = p.get("permalink") or ""
            permalink = (
                f"https://www.reddit.com{permalink_path}"
                if permalink_path
                else f"https://www.reddit.com/r/{sub}/comments/{pid}/"
            )
            if dedup and not dedup.should_write("reddit", permalink, score):
                continue

            full_text = f"{p.get('title') or ''}\n\n{p.get('selftext') or ''}".strip()
            date_iso = utc_iso_from_unix(p.get("created_utc") or 0)
            post_model = detect_model(full_text, keywords)

            write_record(
                corpus_dir,
                Record(
                    source="reddit",
                    source_subkey=f"r/{sub}",
                    post_id=pid,
                    permalink=permalink,
                    date=date_iso,
                    model_mentioned=post_model,
                    post_text=full_text,
                    score=score,
                    is_comment=False,
                    parent_id=None,
                    mentions_release_event=detect_release_event(
                        full_text, date_iso, releases
                    ),
                ),
            )
            n_records += 1
            kept += 1

        print(f"  kept {kept}/{len(children)} posts (floor={floor})")
        time.sleep(SLEEP_SECONDS)

    # All-subs-failed guard. In CI, Reddit may return 403 for shared runner IPs.
    # Without this guard, the cron would silently report "0 records" and
    # the build would go green. Better to fail loudly so we can debug.
    if subs and n_subs_succeeded == 0:
        raise RuntimeError(
            f"reddit-recent unauth: ALL {len(subs)} subreddits failed. "
            "Reddit is likely blocking this IP. "
            "Check the User-Agent and consider running from a different network."
        )

    print(f"[reddit_recent_unauth] total: {n_records}", flush=True)
    return n_records


# ---------------------------------------------------------------------------
# PRAW path — opt-in via env. Hard-fails on auth error.
# ---------------------------------------------------------------------------

def _scrape_via_praw(
    corpus_dir: Path,
    config_dir: Path,
    dedup: DedupIndex | None,
) -> int:
    import praw  # imported here so the unauth path doesn't need praw installed

    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", UA),
    )

    with open(config_dir / "subreddits.json") as f:
        cfg = json.load(f)
    subs: list[str] = cfg["subreddits"]
    sel = cfg["selection_strategy"]
    floor: int = sel.get("min_score_floor", 5)
    comment_floor: int = sel.get("comment_score_floor", 3)

    keywords = load_model_keywords(config_dir)
    releases = load_releases(config_dir)

    n_records = 0
    for sub in subs:
        print(f"[reddit_recent_praw] r/{sub}", flush=True)
        try:
            sr = reddit.subreddit(sub)
            posts = list(sr.top(time_filter="month", limit=None)) + list(
                sr.hot(limit=200)
            )
        except Exception as e:
            # Fail loud — don't silently fall back to unauth when creds were set.
            raise RuntimeError(
                f"PRAW failed for r/{sub}: {e}. "
                "Unset REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET to use the unauth path."
            ) from e

        seen_local: set[str] = set()
        for p in posts:
            if p.id in seen_local:
                continue
            seen_local.add(p.id)
            if (p.score or 0) < floor:
                continue

            permalink = f"https://www.reddit.com{p.permalink}"
            date_iso = utc_iso_from_unix(p.created_utc)
            full_text = f"{p.title}\n\n{p.selftext or ''}".strip()
            score = int(p.score or 0)

            if dedup and not dedup.should_write("reddit", permalink, score):
                continue

            post_model = detect_model(full_text, keywords)
            write_record(
                corpus_dir,
                Record(
                    source="reddit",
                    source_subkey=f"r/{sub}",
                    post_id=p.id,
                    permalink=permalink,
                    date=date_iso,
                    model_mentioned=post_model,
                    post_text=full_text,
                    score=score,
                    is_comment=False,
                    parent_id=None,
                    mentions_release_event=detect_release_event(
                        full_text, date_iso, releases
                    ),
                ),
            )
            n_records += 1

            # PRAW path includes comments. Note: comment-fetch errors are
            # caught and logged (NOT raised) — comment coverage is best-effort
            # while post coverage is required. A single archived/locked post
            # shouldn't kill the whole sub. If you want stricter behavior,
            # change the except below to re-raise.
            try:
                p.comments.replace_more(limit=0)
                for c in p.comments.list():
                    cscore = int(getattr(c, "score", 0) or 0)
                    if cscore < comment_floor:
                        continue
                    cbody = getattr(c, "body", "") or ""
                    if not cbody or cbody in ("[deleted]", "[removed]"):
                        continue
                    cpermalink = f"https://www.reddit.com{c.permalink}"
                    cdate = utc_iso_from_unix(c.created_utc)
                    if dedup and not dedup.should_write("reddit", cpermalink, cscore):
                        continue
                    write_record(
                        corpus_dir,
                        Record(
                            source="reddit",
                            source_subkey=f"r/{sub}",
                            post_id=c.id,
                            permalink=cpermalink,
                            date=cdate,
                            model_mentioned=detect_model(
                                cbody, keywords, parent_model=post_model
                            ),
                            post_text=cbody,
                            score=cscore,
                            is_comment=True,
                            parent_id=str(getattr(c, "parent_id", "") or p.id),
                            mentions_release_event=detect_release_event(
                                cbody, cdate, releases
                            ),
                        ),
                    )
                    n_records += 1
            except Exception as e:
                print(f"  comment fetch failed for {p.id}: {e}")

    print(f"[reddit_recent_praw] total: {n_records}", flush=True)
    return n_records


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape_reddit_recent(
    corpus_dir: Path,
    config_dir: Path,
    dedup: DedupIndex | None = None,
) -> int:
    """Plugs the ~24-48h freshness gap on Reddit posts.

    Default: unauthenticated /r/<sub>/new.json (no credentials needed, posts only).
    PRAW path only when REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET are set in env.
    PRAW path includes comments; unauth path does not.
    """
    if _has_praw_creds():
        return _scrape_via_praw(corpus_dir, config_dir, dedup)
    return _scrape_via_unauth(corpus_dir, config_dir, dedup)
