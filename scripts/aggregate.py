import hashlib
import html
import os
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Dict, List

import feedparser
import yaml
from dateutil import parser as dtparser

ROOT = os.path.dirname(os.path.dirname(__file__))
CFG_PATH = os.path.join(ROOT, "feeds.yaml")
OUT_PATH = os.path.join(ROOT, "feed.xml")


def strip_control_chars(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", s)


def esc(s: str) -> str:
    return html.escape(strip_control_chars(s or ""), quote=False)


def stable_guid(entry: Dict[str, Any], link: str) -> str:
    raw = entry.get("id") or entry.get("guid") or link or (
        f"{entry.get('title','')}|{entry.get('published','')}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_dt(entry: Dict[str, Any]) -> datetime:
    for k in ("published", "updated"):
        v = entry.get(k)
        if v:
            try:
                dt = dtparser.parse(v)
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def main():
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    feeds = cfg["feeds"]
    max_items = cfg.get("max_items", 80)

    items = []
    seen = set()

    for feed in feeds:
        parsed = feedparser.parse(feed["url"])

        for e in parsed.entries:
            link = e.get("link")
            if not link:
                continue

            guid = stable_guid(e, link)
            if guid in seen:
                continue
            seen.add(guid)

            dt = parse_dt(e)
            title = strip_control_chars(e.get("title", "(no title)"))
            summary = strip_control_chars(
                e.get("summary", "") or e.get("description", "")
            )

            items.append(
                {
                    "guid": guid,
                    "dt": dt,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "source": feed["name"],
                }
            )

    items.sort(key=lambda x: x["dt"], reverse=True)
    items = items[:max_items]

    now = datetime.now(timezone.utc)

    rss = []
    rss.append('<?xml version="1.0" encoding="UTF-8"?>')
    rss.append('<rss version="2.0">')
    rss.append("<channel>")
    rss.append(f"<title>{esc(cfg['title'])}</title>")
    rss.append(f"<description>{esc(cfg['description'])}</description>")
    rss.append(f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>")

    for it in items:
        rss.append("<item>")
        rss.append(f"<title>{esc(it['source'] + ' | ' + it['title'])}</title>")
        rss.append(f"<link>{esc(it['link'])}</link>")
        rss.append(f"<guid isPermaLink=\"false\">{it['guid']}</guid>")
        rss.append(f"<pubDate>{format_datetime(it['dt'])}</pubDate>")
        rss.append(f"<description>{esc(it['summary'])}</description>")
        rss.append("</item>")

    rss.append("</channel>")
    rss.append("</rss>")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(rss))

    print("Feed generated.")


if __name__ == "__main__":
    main()
