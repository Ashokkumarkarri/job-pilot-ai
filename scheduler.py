import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml
from agent.exp_filter import has_experience_requirement
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ── Pre-filters: applied before LLM scoring to skip obviously bad jobs instantly ──
INTERNSHIP_TITLE_RE = re.compile(
    r"\b(intern(ship)?|internships|trainee\s+program|apprentice(ship)?)\b",
    re.IGNORECASE,
)
SENIOR_TITLE_RE = re.compile(
    r"\b(senior|sr\.?\s|lead\s|principal|staff\s+eng|engineering\s+manager|"
    r"director|head\s+of|vice\s+pres|vp\s+of|architect(?!\s+as))\b",
    re.IGNORECASE,
)
IRRELEVANT_TITLE_RE = re.compile(
    r"\b(android|flutter|ios\s+dev|swift\s+dev|kotlin|"
    r"devops|sre\s+|site\s+reliability|data\s+scientist|data\s+engineer|"
    r"machine\s+learning\s+eng|pyspark|salesforce|sap\s+|"
    r"manufacturing|quality\s+assurance|qa\s+eng|guard\b|"
    r"transportation\s+rep|relationship\s+manager)\b",
    re.IGNORECASE,
)


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def run_pipeline():
    from scrapers.linkedin_indeed import scrape_linkedin_indeed
    from scrapers.remoteok        import scrape_remoteok
    from scrapers.remotive        import scrape_remotive
    from scrapers.arbeitnow       import scrape_arbeitnow
    from scrapers.jobicy          import scrape_jobicy
    from scrapers.workingnomads   import scrape_workingnomads
    from scrapers.hackernews      import scrape_hackernews
    from scrapers.shine           import scrape_shine
    from scrapers.internshala     import scrape_internshala
    from scrapers.foundit         import scrape_foundit
    from scrapers.timesjobs       import scrape_timesjobs
    from agent.resume_matcher import score_job, load_resume
    from agent.contact_finder import find_contact
    from agent.email_drafter  import draft_email_lite
    from agent.gmail_drafts   import save_all_drafts
    from storage.database     import job_exists, insert_job, update_contact, update_draft_email, get_relevant_jobs
    from storage.excel_export import export_to_excel

    config = load_config()
    threshold = config["matching"]["relevance_threshold"]

    import io, os as _os
    _log_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "pipeline_log.txt")
    def _plog(msg):
        from datetime import datetime as _dt
        line = f"[{_dt.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line)
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(line + "\n")

    _plog("=" * 55)
    _plog("  JobPilot AI  Pipeline Starting")
    _plog("=" * 55)

    # 1. Load resume (sets internal state used by scorer)
    print("\n[1/6] Loading resume...")
    load_resume(config["resume"]["path"])

    # Reset Groq fallback flag so each run starts fresh (Groq quota may have refilled)
    try:
        from agent.resume_matcher import reset_groq_state
        reset_groq_state()
    except Exception:
        pass

    # 2. Scrape all sources IN PARALLEL (I/O-bound — big time saving)
    print("\n[2/6] Scraping jobs from all sources (parallel)...")
    all_jobs = []

    sources = [
        ("LinkedIn/Indeed/Google", scrape_linkedin_indeed),
        ("RemoteOK",       scrape_remoteok),
        ("Remotive",       scrape_remotive),
        ("Arbeitnow",      scrape_arbeitnow),
        ("Jobicy",         scrape_jobicy),
        ("WorkingNomads",  scrape_workingnomads),
        ("HackerNews",     scrape_hackernews),
        ("Shine",          scrape_shine),
        ("Internshala",    scrape_internshala),
        ("Foundit",        scrape_foundit),
        ("TimesJobs",      scrape_timesjobs),
        # Naukri — Cloudflare blocks all approaches (requests + Playwright), disabled
        # Hirist — SPA blocks headless browsers entirely, disabled
    ]

    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    _print_lock = threading.Lock()

    def _run_scraper(item):
        name, fn = item
        try:
            jobs = fn()
            with _print_lock:
                print(f"  {name}: {len(jobs)} jobs")
            return jobs
        except Exception as e:
            with _print_lock:
                print(f"  {name}: ERROR — {e}")
            return []

    with ThreadPoolExecutor(max_workers=len(sources)) as _ex:
        for batch in _ex.map(_run_scraper, sources):
            all_jobs.extend(batch)

    # Global dedup across all sources
    seen_keys = set()
    unique_jobs = []
    for job in all_jobs:
        key = f"{job.get('company','').lower()}|{job.get('title','').lower()}"
        if job["job_id"] not in seen_keys and key not in seen_keys:
            seen_keys.add(job["job_id"])
            seen_keys.add(key)
            unique_jobs.append(job)

    new_jobs = [j for j in unique_jobs if not job_exists(j["job_id"])]

    # Drop jobs older than 14 days (stale postings) — only when date is known
    from datetime import datetime as _dt2, timedelta as _td2
    _cutoff = _dt2.now() - _td2(days=14)
    def _fresh(job):
        dp = str(job.get("date_posted") or "").strip()
        if not dp or dp in ("nan", "None"):
            return True
        try:
            return _dt2.strptime(dp[:10], "%Y-%m-%d") >= _cutoff
        except Exception:
            return True
    before_fresh = len(new_jobs)
    new_jobs = [j for j in new_jobs if _fresh(j)]
    stale_dropped = before_fresh - len(new_jobs)
    if stale_dropped:
        print(f"  Dropped {stale_dropped} stale jobs (>14 days old)")

    _plog(f"  Total scraped: {len(unique_jobs)} unique | New: {len(new_jobs)}")

    if not new_jobs:
        _plog("  No new jobs. Exporting existing data...")
        export_to_excel(config["storage"]["excel_path"], threshold)
        return

    # 3. Score jobs — pre-filters at top, Qwen3 only for genuine candidates
    print(f"\n[3/6] Scoring {len(new_jobs)} new jobs...")
    relevant = []

    for i, job in enumerate(new_jobs, 1):
        title = job.get("title", "")
        if INTERNSHIP_TITLE_RE.search(title):
            job["relevance_score"]     = 1
            job["match_reason"]        = "Internship position — skipped (targeting full-time roles)"
            job["internship_friendly"] = 0
            job["experience_required"] = "internship"
            insert_job(job)
            print(f"  [{i:>3}/{len(new_jobs)}]  1/10 [skip] [INTERNSHIP] {title[:40]} @ {job.get('company','')[:25]}")
            continue

        if SENIOR_TITLE_RE.search(title):
            job["relevance_score"]     = 1
            job["match_reason"]        = "Senior/lead role — skipped (targeting 0-1 year experience)"
            job["internship_friendly"] = 0
            job["experience_required"] = "senior"
            insert_job(job)
            print(f"  [{i:>3}/{len(new_jobs)}]  1/10 [skip] [SENIOR] {title[:40]} @ {job.get('company','')[:25]}")
            continue

        if IRRELEVANT_TITLE_RE.search(title):
            job["relevance_score"]     = 1
            job["match_reason"]        = "Irrelevant tech/role — skipped"
            job["internship_friendly"] = 0
            job["experience_required"] = "irrelevant"
            insert_job(job)
            print(f"  [{i:>3}/{len(new_jobs)}]  1/10 [skip] [IRRELEVANT] {title[:40]} @ {job.get('company','')[:25]}")
            continue

        desc = job.get("description", "") or ""
        if has_experience_requirement(desc):
            job["relevance_score"]     = 1
            job["match_reason"]        = "Description requires 2+ years experience — skipped"
            job["internship_friendly"] = 0
            job["experience_required"] = "2+ years"
            insert_job(job)
            print(f"  [{i:>3}/{len(new_jobs)}]  1/10 [skip] [EXP>1YR] {title[:40]} @ {job.get('company','')[:25]}")
            continue

        try:
            result = score_job(job)
            score   = int(result.get("score", 0))
            reason  = result.get("reason", "")
            intern_f = 1 if result.get("internship_friendly") else 0
            exp_req  = result.get("experience_required", "")

            job["relevance_score"]     = score
            job["match_reason"]        = reason
            job["internship_friendly"] = intern_f
            job["experience_required"] = exp_req

            insert_job(job)
            tag = "MATCH" if score >= threshold else "skip"
            inf = " [INTERN-OK]" if intern_f else ""
            print(f"  [{i:>3}/{len(new_jobs)}] {score:>2}/10 [{tag}]{inf} {title[:40]} @ {job.get('company','')[:25]}")

            if score >= threshold:
                relevant.append(job)

        except Exception as e:
            print(f"  [{i:>3}/{len(new_jobs)}] ERROR scoring: {e}")

    _plog(f"  Relevant (score >= {threshold}): {len(relevant)}")

    # 4. Description filler — BEFORE email so hidden exp requirements are caught first
    try:
        from agent.description_filler import run_filler
        _plog(f"\n[4/6] Auto-filling descriptions for no-desc matched jobs...")
        run_filler(limit=40, rescore=True)
    except Exception as e:
        print(f"[!] Description filler error: {e}")

    # Reload relevant from DB — filler may have downgraded some jobs
    import sqlite3 as _sq3
    _conn = _sq3.connect("jobs.db")
    _conn.row_factory = _sq3.Row
    _rel_ids = [j["job_id"] for j in relevant]
    if _rel_ids:
        _ph = ",".join("?" * len(_rel_ids))
        _rows = _conn.execute(
            f"SELECT * FROM jobs WHERE job_id IN ({_ph}) AND relevance_score >= ?",
            _rel_ids + [threshold]
        ).fetchall()
        relevant = [dict(r) for r in _rows]
    _conn.close()
    _plog(f"  After description filler: {len(relevant)} still relevant")

    # Export full sheet
    export_to_excel(config["storage"]["excel_path"], threshold)

    # Email #1 — APPLY NOW (fast, sent before contact search)
    if relevant:
        from agent.notify_email import send_report
        _plog(f"[+] Sending APPLY NOW email ({len(relevant)} jobs)...")
        ok = send_report(relevant, tag="[APPLY NOW]")
        _plog(f"[+] Email #1 {'sent OK' if ok else 'FAILED'}")
    else:
        _plog("[+] No relevant jobs this run — skipping email.")

    # 5. Find HR contacts
    print(f"\n[5/6] Finding contacts for {len(relevant)} relevant jobs...")
    for job in relevant:
        website = job.get("company_website", "")
        contacts = find_contact(website, company_name=job.get("company", ""))
        if contacts.get("email_1"):
            update_contact(job["job_id"], contacts)
            job.update(contacts)
            info = contacts["email_1"]
            if contacts.get("phone"):
                info += f" | {contacts['phone']}"
            print(f"  {job['company'][:30]}: {info}")
        else:
            print(f"  {job['company'][:30]}: no contact found")

    # 6. Draft + Gmail Drafts — only for jobs where HR contact was found
    jobs_with_contact = [j for j in relevant if j.get("hr_email")]
    print(f"\n[6/6] Drafting emails for {len(jobs_with_contact)} jobs with HR contact...")
    for job in jobs_with_contact:
        try:
            draft = draft_email_lite(job)
            update_draft_email(job["job_id"], draft)
            job["draft_email"] = draft
            print(f"  Drafted: {job['title'][:40]} @ {job['company'][:25]}")
        except Exception as e:
            print(f"  Draft error [{job['company']}]: {e}")

    save_all_drafts(jobs_with_contact)

    # Email #2 — +HR Contacts (only if at least 1 contact was found)
    if jobs_with_contact:
        _plog(f"[+] Sending HR Contacts email ({len(jobs_with_contact)} contacts found)...")
        ok = send_report(relevant, tag="[+HR Contacts]")
        _plog(f"[+] Email #2 {'sent OK' if ok else 'FAILED'}")
    else:
        _plog("[+] No HR contacts found this run — skipping contacts email.")

    _plog("=" * 55)
    _plog("  Pipeline Complete")
    _plog("=" * 55)


def start_scheduler():
    config = load_config()
    hours = config["scraping"]["interval_hours"]

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger=IntervalTrigger(hours=hours),
        id="jobpilot_pipeline",
        name="JobPilot Pipeline",
    )

    print(f"Scheduler running — every {hours} hours. Ctrl+C to stop.\n")
    run_pipeline()

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    start_scheduler()
