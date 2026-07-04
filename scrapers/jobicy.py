import hashlib
import requests
import yaml

BASE_URL = "https://jobicy.com/api/v2/remote-jobs"
HEADERS  = {"User-Agent": "Mozilla/5.0 (JobPilot job search bot)"}

SEARCH_TAGS = ["react", "typescript", "fullstack"]  # nodejs/javascript return 404 from Jobicy API


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def scrape_jobicy():
    print("  [Jobicy] Fetching remote JS/React jobs...")
    results = []
    seen = set()

    for tag in SEARCH_TAGS:
        try:
            resp = requests.get(
                BASE_URL,
                params={"count": 50, "tag": tag, "industry": "engineering"},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])

            for job in jobs:
                url     = job.get("url", "").strip()
                title   = job.get("jobTitle", "").strip()
                company = job.get("companyName", "").strip()

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
                    "location":        job.get("jobGeo", "Remote"),
                    "source":          "jobicy",
                    "job_url":         url,
                    "description":     job.get("jobExcerpt", "").strip(),
                    "date_posted":     str(job.get("pubDate", ""))[:10],
                    "company_website": job.get("companyUrl", ""),
                })

        except Exception as e:
            print(f"    Jobicy error [{tag}]: {e}")

    print(f"    Jobicy: {len(results)} unique jobs")
    return results
