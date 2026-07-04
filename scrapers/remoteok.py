import hashlib
import time
import requests
import yaml

API_URL = "https://remoteok.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0 (JobPilot job search bot)"}

RELEVANT_TAGS = {
    "react", "node", "nodejs", "javascript", "typescript",
    "mern", "fullstack", "full-stack", "frontend", "mongodb",
    "express", "next.js", "nextjs", "reactnative"
}


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _is_relevant(job):
    tags = [t.lower() for t in job.get("tags", [])]
    title = job.get("position", "").lower()
    combined = " ".join(tags) + " " + title
    return any(kw in combined for kw in RELEVANT_TAGS)


def scrape_remoteok():
    print("  [RemoteOK] Fetching remote jobs...")
    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    RemoteOK error: {e}")
        return []

    # First item is a metadata notice, skip it
    jobs_raw = [j for j in data if isinstance(j, dict) and "position" in j]

    results = []
    seen = set()

    for job in jobs_raw:
        if not _is_relevant(job):
            continue

        url     = job.get("url", "") or f"https://remoteok.com/jobs/{job.get('id','')}"
        title   = job.get("position", "").strip()
        company = job.get("company", "").strip()

        if not url or not title:
            continue

        dedup_key = f"{company.lower()}|{title.lower()}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        job_id = hashlib.md5(url.encode()).hexdigest()
        results.append({
            "job_id":          job_id,
            "title":           title,
            "company":         company,
            "location":        "Remote",
            "source":          "remoteok",
            "job_url":         url,
            "description":     job.get("description", "").strip(),
            "date_posted":     str(job.get("date", ""))[:10],
            "company_website": job.get("company_website", ""),
        })

    print(f"    RemoteOK: {len(results)} relevant remote jobs")
    return results
