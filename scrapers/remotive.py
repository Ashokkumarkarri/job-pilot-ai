import hashlib
import requests
import yaml

BASE_URL = "https://remotive.com/api/remote-jobs"
HEADERS  = {"User-Agent": "Mozilla/5.0 (JobPilot job search bot)"}

SEARCH_TERMS = ["react developer", "node.js developer", "mern stack", "full stack javascript", "react native"]


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def scrape_remotive():
    print("  [Remotive] Fetching remote developer jobs...")
    results = []
    seen = set()

    for term in SEARCH_TERMS:
        try:
            resp = requests.get(
                BASE_URL,
                params={"category": "software-dev", "search": term, "limit": 50},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])

            for job in jobs:
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
                    "location":        job.get("candidate_required_location", "Remote"),
                    "source":          "remotive",
                    "job_url":         url,
                    "description":     job.get("description", "").strip()[:3000],
                    "date_posted":     str(job.get("publication_date", ""))[:10],
                    "company_website": job.get("company_logo", ""),
                })

        except Exception as e:
            print(f"    Remotive error [{term}]: {e}")

    print(f"    Remotive: {len(results)} unique jobs")
    return results
