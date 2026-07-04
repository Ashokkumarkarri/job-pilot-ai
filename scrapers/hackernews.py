import hashlib
import re
import requests
from datetime import datetime, timezone

# HN "Who is Hiring" thread is posted the first weekday of each month.
# We query Algolia's HN API to find the latest one and parse comments.

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"
ALGOLIA_ITEM   = "https://hn.algolia.com/api/v1/items/{id}"
HEADERS        = {"User-Agent": "Mozilla/5.0 (JobPilot job search bot)"}

RELEVANT = {
    "react", "node", "nodejs", "mern", "javascript", "typescript",
    "fullstack", "full stack", "frontend", "next.js", "nextjs",
    "express", "mongodb", "remote"
}

SKIP = {"senior", "staff", "principal", "lead", "manager", "director",
        "architect", "vp ", "head of", "10+ years", "8+ years", "7+ years",
        "5+ years", "6+ years"}


def _find_latest_hiring_thread():
    try:
        resp = requests.get(
            ALGOLIA_SEARCH,
            params={
                "query": "Ask HN: Who is hiring?",
                "tags": "story,ask_hn",
                "hitsPerPage": 5,
            },
            headers=HEADERS,
            timeout=15,
        )
        hits = resp.json().get("hits", [])
        # Filter to posts by whoishiring user or with exact title
        for hit in hits:
            title = hit.get("title", "")
            if "Who is hiring?" in title and hit.get("author") == "whoishiring":
                return hit.get("objectID")
        # Fallback: just return first result
        return hits[0]["objectID"] if hits else None
    except Exception:
        return None


def _is_relevant(text):
    lower = text.lower()
    if not any(kw in lower for kw in RELEVANT):
        return False
    if any(kw in lower for kw in SKIP):
        return False
    return True


def scrape_hackernews():
    print("  [HackerNews] Fetching Who's Hiring thread...")
    results = []

    thread_id = _find_latest_hiring_thread()
    if not thread_id:
        print("    Could not find HN hiring thread.")
        return []

    try:
        resp = requests.get(
            ALGOLIA_ITEM.format(id=thread_id),
            headers=HEADERS,
            timeout=20,
        )
        data = resp.json()
        children = data.get("children", [])
    except Exception as e:
        print(f"    HN fetch error: {e}")
        return []

    seen = set()
    for comment in children:
        text = comment.get("text", "") or ""
        # Strip HTML tags
        clean = re.sub(r"<[^>]+>", " ", text).strip()

        if not clean or not _is_relevant(clean):
            continue

        # Extract company name (first line usually)
        first_line = clean.split("\n")[0][:80].strip()
        company = first_line.split("|")[0].split("-")[0].strip()[:50]

        # Build a unique URL for this comment
        comment_id = comment.get("id", "")
        url = f"https://news.ycombinator.com/item?id={comment_id}"

        dedup_key = f"hn|{comment_id}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        job_id = hashlib.md5(url.encode()).hexdigest()
        results.append({
            "job_id":          job_id,
            "title":           first_line[:100],
            "company":         company,
            "location":        "Remote / Various",
            "source":          "hackernews",
            "job_url":         url,
            "description":     clean[:3000],
            "date_posted":     str(comment.get("created_at", ""))[:10],
            "company_website": "",
        })

    print(f"    HackerNews: {len(results)} relevant job posts")
    return results
