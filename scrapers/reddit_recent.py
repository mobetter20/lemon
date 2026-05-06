"""Reddit recent scraper via PRAW (last ~30 days where pullpush often lags).

Required env:
  REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT (optional but recommended)

Read-only script app — no write scopes needed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

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


def _make_reddit():
    import praw

    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get(
        "REDDIT_USER_AGENT", "lemon-corpus-builder/0.1 (by lemon-project)"
    )
    if not (client_id and client_secret):
        raise RuntimeError(
            "Missing REDDIT_CLIENT_ID and/or REDDIT_CLIENT_SECRET. "
            "Create a script-type Reddit app at https://www.reddit.com/prefs/apps "
            "and export the credentials before running."
        )
    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )


def scrape_reddit_recent(
    corpus_dir: Path,
    config_dir: Path,
    dedup: DedupIndex | None = None,
) -> int:
    with open(config_dir / "subreddits.json") as f:
        cfg = json.load(f)
    subs: list[str] = cfg["subreddits"]
    sel = cfg["selection_strategy"]
    floor: int = sel.get("min_score_floor", 5)
    comment_floor: int = sel.get("comment_score_floor", 3)

    keywords = load_model_keywords(config_dir)
    releases = load_releases(config_dir)

    reddit = _make_reddit()
    n_records = 0

    for sub in subs:
        print(f"[reddit_recent] r/{sub}", flush=True)
        try:
            sr = reddit.subreddit(sub)
            posts = list(sr.top(time_filter="month", limit=None)) + list(
                sr.hot(limit=200)
            )
        except Exception as e:
            print(f"  failed: {e}")
            continue

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
                            model_mentioned=detect_model(cbody, keywords, parent_model=post_model),
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

    print(f"[reddit_recent] total: {n_records}", flush=True)
    return n_records
