import json
import os
import re
import sqlite3

import pdfplumber
import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

_resume_text   = None
_gemini_failed = False
_groq_failed   = False

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def reset_llm_state():
    global _gemini_failed, _groq_failed
    _gemini_failed = False
    _groq_failed   = False


reset_groq_state = reset_llm_state  # backwards-compat alias


def _get_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def load_resume(path=None):
    global _resume_text
    if path is None:
        path = _get_config()["resume"]["path"]
    with pdfplumber.open(path) as pdf:
        _resume_text = "\n".join(
            page.extract_text() for page in pdf.pages if page.extract_text()
        )
    print(f"Resume loaded: {len(_resume_text)} characters")
    return _resume_text


# ── Prompts ──────────────────────────────────────────────────────────────────

_RULES = """SCORING (Kumar Naidu Karri — MERN fresher, 0-1yr target):
SKILLS: React.js Node.js Express.js MongoDB JavaScript TypeScript REST APIs Git HTML/CSS Tailwind
9-10: MERN/React/Node + fresher/0-1yr + full-time permanent
7-8:  React or Node, junior level, <=1yr exp required
5-6:  JS-adjacent, exp unclear
1-3:  AUTO if ANY → 2+yrs mentioned | senior/lead/architect title | internship | wrong stack (Java/.NET/PHP/Python/Android/iOS/DevOps/Data)
CRITICAL: if description mentions 2+ years ANYWHERE → score 1-3, no exceptions."""


def _trim_desc(desc, max_chars=800):
    desc = str(desc or "").strip()
    if len(desc) <= max_chars:
        return desc
    return desc[:600] + "...[cut]..." + desc[-200:]


def _build_single_prompt(job):
    return f"""{_RULES}

Title: {job.get('title','')}
Company: {job.get('company','')}
Location: {job.get('location','')}
Description:
{_trim_desc(job.get('description',''))}

Reply with JSON only:
{{"score":<1-10>,"reason":"<one sentence>","internship_friendly":<bool>,"experience_required":"<exact phrase or not mentioned>"}}"""


def _build_batch_prompt(jobs):
    blocks = []
    for i, job in enumerate(jobs, 1):
        blocks.append(
            f"[JOB {i}] {job.get('title','')} @ {job.get('company','')}\n"
            f"Location: {job.get('location','')}\n"
            f"{_trim_desc(job.get('description',''))}"
        )
    jobs_text = "\n\n".join(blocks)

    return f"""{_RULES}

{jobs_text}

Return a JSON array with exactly {len(jobs)} objects in order:
[{{"job":1,"score":<1-10>,"reason":"<one sentence>","internship_friendly":<bool>,"experience_required":"<phrase or not mentioned>"}},...]"""


# ── Providers ─────────────────────────────────────────────────────────────────

def _score_via_gemini(job, model):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    url = GEMINI_API_URL.format(model=model) + f"?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": _build_single_prompt(job)}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"])


def _score_batch_via_gemini(jobs, model):
    """Score a list of jobs in one API call. Returns list of result dicts."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    url = GEMINI_API_URL.format(model=model) + f"?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": _build_batch_prompt(jobs)}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    results = json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
    if not isinstance(results, list) or len(results) != len(jobs):
        raise ValueError(f"Expected {len(jobs)} results, got {len(results) if isinstance(results, list) else type(results)}")
    return results


def _score_via_groq(job, model):
    from groq import Groq
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set")
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _build_single_prompt(job)}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _score_via_ollama(job, model):
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": "/no_think\n" + _build_single_prompt(job),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "think": False},
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = re.sub(r"<think>.*?</think>", "", resp.json()["response"], flags=re.DOTALL).strip()
    return json.loads(raw)


def _score_via_ollama_safe(job, model):
    try:
        return _score_via_ollama(job, model)
    except requests.exceptions.ReadTimeout:
        short = dict(job)
        short["description"] = str(job.get("description", "") or "")[:400]
        try:
            return _score_via_ollama(short, model)
        except Exception:
            pass
    except Exception:
        pass
    return {"score": 0, "reason": "Scoring failed", "internship_friendly": False,
            "experience_required": "unknown"}


def _is_quota_error(e):
    err = str(e).lower()
    return any(kw in err for kw in [
        "429", "rate_limit", "rate limit", "quota", "resource_exhausted",
        "limit exceeded", "too many requests", "connection", "timeout",
        "503", "502", "500",
    ])


# ── Cache ─────────────────────────────────────────────────────────────────────

def check_score_cache(title, company, days=7):
    """Return a cached result dict if same title+company scored recently, else None."""
    try:
        conn = sqlite3.connect("jobs.db")
        row = conn.execute("""
            SELECT relevance_score, match_reason, internship_friendly, experience_required
            FROM jobs
            WHERE LOWER(TRIM(title))   = LOWER(TRIM(?))
              AND LOWER(TRIM(company)) = LOWER(TRIM(?))
              AND date_scraped >= datetime('now', ? || ' days')
              AND relevance_score > 0
            ORDER BY date_scraped DESC LIMIT 1
        """, (title, company, f"-{days}")).fetchone()
        conn.close()
        if row:
            return {
                "score": row[0],
                "reason": f"[cached] {row[1]}",
                "internship_friendly": bool(row[2]),
                "experience_required": row[3] or "unknown",
            }
    except Exception:
        pass
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def score_job(job):
    """Score a single job. Used by description_filler. Falls back Gemini→Groq→Ollama."""
    global _gemini_failed, _groq_failed

    if _resume_text is None:
        load_resume()

    config       = _get_config()
    use_ollama   = config["matching"].get("use_ollama", False)
    gemini_model = config["matching"].get("gemini_model", "gemini-2.5-flash")
    groq_model   = config["matching"].get("groq_model", "llama-3.1-8b-instant")
    ollama_model = config["matching"].get("ollama_model", "qwen3:8b")

    if use_ollama:
        return _score_via_ollama_safe(job, ollama_model)

    if not _gemini_failed:
        try:
            return _score_via_gemini(job, gemini_model)
        except Exception as e:
            print(f"    Gemini error ({str(e)[:60]}) — trying Groq...")
            _gemini_failed = True

    if not _groq_failed:
        try:
            return _score_via_groq(job, groq_model)
        except Exception as e:
            print(f"    Groq error ({str(e)[:60]}) — falling back to Ollama...")
            _groq_failed = True

    return _score_via_ollama_safe(job, ollama_model)


def score_jobs_batch(jobs, batch_size=5):
    """
    Score a list of jobs using batch API calls (5 per request).
    Returns a list of result dicts in the same order as input.
    Falls back Gemini→Groq→Ollama per batch.
    """
    global _gemini_failed, _groq_failed

    if _resume_text is None:
        load_resume()

    config       = _get_config()
    use_ollama   = config["matching"].get("use_ollama", False)
    gemini_model = config["matching"].get("gemini_model", "gemini-2.5-flash")
    groq_model   = config["matching"].get("groq_model", "llama-3.1-8b-instant")
    ollama_model = config["matching"].get("ollama_model", "qwen3:8b")

    all_results = []

    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(jobs) + batch_size - 1) // batch_size
        print(f"    Batch {batch_num}/{total_batches} ({len(batch)} jobs)...", end=" ", flush=True)

        if use_ollama:
            for job in batch:
                all_results.append(_score_via_ollama_safe(job, ollama_model))
            print("Ollama")
            continue

        # Try Gemini batch
        if not _gemini_failed:
            try:
                results = _score_batch_via_gemini(batch, gemini_model)
                all_results.extend(results)
                print("Gemini OK")
                continue
            except Exception as e:
                if _is_quota_error(e):
                    print(f"Gemini quota — switching to Groq...")
                else:
                    print(f"Gemini error — switching to Groq...")
                _gemini_failed = True

        # Try Groq individually (no batch endpoint for Groq)
        if not _groq_failed:
            try:
                for job in batch:
                    all_results.append(_score_via_groq(job, groq_model))
                print("Groq OK")
                continue
            except Exception as e:
                if _is_quota_error(e):
                    print(f"Groq quota — falling back to Ollama...")
                else:
                    print(f"Groq error — falling back to Ollama...")
                _groq_failed = True

        # Ollama fallback
        for job in batch:
            all_results.append(_score_via_ollama_safe(job, ollama_model))
        print("Ollama")

    return all_results
