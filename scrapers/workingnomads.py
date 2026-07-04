import hashlib
import requests
import yaml

BASE_URL = "https://www.workingnomads.com/api/exposed_jobs/"
HEADERS  = {"User-Agent": "Mozilla/5.0 (JobPilot job search bot)"}

RELEVANT = {
    "react", "node", "nodejs", "javascript", "typescript",
    "mern", "fullstack", "full stack", "frontend", "mongodb",
    "express", "next.js", "nextjs", "web developer"
}


def _is_relevant(job):
    text = (job.get("title", "") + " " + job.get("category", "")).lower()
    return any(kw in text for kw in RELEVANT)


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def scrape_workingnomads():
    print("  [WorkingNomads] Fetching remote jobs...")
    results = []
    seen = set()

    try:
        resp = requests.get(BASE_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        jobs = resp.json()

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
                "location":        "Remote",
                "source":          "workingnomads",
                "job_url":         url,
                "description":     job.get("description", "").strip()[:3000],
                "date_posted":     str(job.get("pub_date", ""))[:10],
                "company_website": "",
            })

    except Exception as e:
        print(f"    WorkingNomads error: {e}")

    print(f"    WorkingNomads: {len(results)} relevant jobs")
    return results
