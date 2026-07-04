import hashlib
import requests
import yaml

BASE_URL = "https://arbeitnow.com/api/job-board-api"
HEADERS  = {"User-Agent": "Mozilla/5.0 (JobPilot job search bot)"}

KEYWORDS = ["react", "node", "mern", "full stack", "javascript", "frontend react"]

RELEVANT = {
    "react", "node", "nodejs", "javascript", "typescript",
    "mern", "fullstack", "frontend", "mongodb", "express",
    "next.js", "nextjs", "vue", "angular"
}


def _is_relevant(job):
    text = (job.get("title", "") + " " + " ".join(job.get("tags", []))).lower()
    return any(kw in text for kw in RELEVANT)


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def scrape_arbeitnow():
    print("  [Arbeitnow] Fetching global remote tech jobs...")
    results = []
    seen = set()

    try:
        resp = requests.get(BASE_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        jobs = resp.json().get("data", [])

        for job in jobs:
            if not _is_relevant(job):
                continue

            url     = job.get("url", "").strip()
            title   = job.get("title", "").strip()
            company = job.get("company_name", "").strip()

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
                "location":        job.get("location", "Remote"),
                "source":          "arbeitnow",
                "job_url":         url,
                "description":     job.get("description", "").strip()[:3000],
                "date_posted":     str(job.get("created_at", ""))[:10],
                "company_website": "",
            })

    except Exception as e:
        print(f"    Arbeitnow error: {e}")

    print(f"    Arbeitnow: {len(results)} relevant jobs")
    return results
