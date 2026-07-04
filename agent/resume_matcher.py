import json
import os

import pdfplumber
import requests
import yaml
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_groq_client  = None
_resume_text  = None
_groq_failed  = False   # Once True for a run, all scoring goes to Ollama


def reset_groq_state():
    """Call at the start of each pipeline run so Groq is retried (quota may have refilled)."""
    global _groq_failed
    _groq_failed = False


def _get_groq():
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in .env file.")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


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


def _build_prompt(job):
    desc_raw = str(job.get("description", "") or "")
    # Send up to 1400 chars but always include the LAST 300 chars of description
    # (experience requirements often appear at the end)
    if len(desc_raw) > 1400:
        desc_for_prompt = desc_raw[:1100] + "\n...[truncated]...\n" + desc_raw[-300:]
    else:
        desc_for_prompt = desc_raw

    return f"""You are a strict job relevance evaluator for Kumar Naidu Karri — a MERN Full Stack Developer fresher (React, Node.js, MongoDB, Express). He has 1 year total experience (9 months internship + 3 months full-time). He is targeting ONLY 0-1 year / fresher / junior roles.

CANDIDATE SKILLS: React.js, Node.js, Express.js, MongoDB, JavaScript, TypeScript, REST APIs, Git, HTML/CSS, Tailwind CSS.

JOB TO EVALUATE:
Title: {job.get("title", "")}
Company: {job.get("company", "")}
Location: {job.get("location", "")}
Description:
{desc_for_prompt}

━━━ STEP 1: EXPERIENCE CHECK (do this FIRST before scoring) ━━━
Scan the ENTIRE description above for ANY of these patterns:
  • "X years", "X+ years", "X yrs", "X to Y years" where X >= 2
  • "minimum X years", "at least X years", "requires X years" where X >= 2
  • "should have X years", "we need X years", "X years of experience" where X >= 2
  • "experience: X years", "experience required: X+" where X >= 2

If ANY such pattern is found with X >= 2, this role requires more experience than the candidate has.

━━━ SCORING RULES ━━━
- Score 9-10: React/Node/MERN stack, 0-1 year or fresher required, full-time permanent role
- Score 7-8:  React or Node.js role, up to 1 year experience, junior level
- Score 5-6:  Adjacent match (JavaScript but no React/Node focus, or unclear requirements)
- Score 3-4:  Wrong stack but some JS overlap, OR 2 years experience required
- Score 1-2:  AUTOMATIC if ANY of: requires 2+ years experience | senior/lead/principal/architect title | position itself is an internship/trainee | unrelated stack (Android/iOS/DevOps/Java/Python/Data Science)

CRITICAL — SCORE MUST BE 1-3 if description anywhere mentions 2+ years, 3 years, 4+ years, minimum 2 years, etc. Do NOT ignore this, even if the rest of the role looks like a good match. The candidate will be auto-rejected by ATS.

Set experience_required to the EXACT phrase from the description, e.g. "2-4 years", "minimum 3 years", "0-1 years", "fresher", "not mentioned".

Respond with valid JSON only:
{{
  "score": <integer 1-10>,
  "reason": "<one sentence — if low score mention the exact experience requirement found>",
  "internship_friendly": <true if description says fresher/0-1 yr/entry-level/junior/recent graduate>,
  "experience_required": "<exact phrase from description, or 'not mentioned'>",
  "matched_skills": ["skill1", "skill2"],
  "missing_skills": ["skill1"]
}}"""


def _score_via_groq(job, model):
    response = _get_groq().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _build_prompt(job)}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _score_via_ollama(job, model):
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": "/no_think\n" + _build_prompt(job),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "think": False},
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json()["response"]
    # Strip any leftover <think>...</think> blocks just in case
    import re
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return json.loads(raw)


def _score_via_ollama_safe(job, model):
    """Ollama with retry on timeout (truncates description)."""
    try:
        return _score_via_ollama(job, model)
    except requests.exceptions.ReadTimeout:
        short_job = dict(job)
        short_job["description"] = str(job.get("description", "") or "")[:400]
        try:
            return _score_via_ollama(short_job, model)
        except Exception:
            return {
                "score": 0,
                "reason": "Scoring timed out — skipped",
                "internship_friendly": False,
                "experience_required": "unknown",
                "matched_skills": [],
                "missing_skills": [],
            }
    except Exception as e:
        return {
            "score": 0,
            "reason": f"Ollama error: {e}",
            "internship_friendly": False,
            "experience_required": "unknown",
            "matched_skills": [],
            "missing_skills": [],
        }


def score_job(job):
    global _groq_failed

    if _resume_text is None:
        load_resume()

    config       = _get_config()
    use_ollama   = config["matching"].get("use_ollama", False)
    groq_model   = config["matching"].get("groq_model", "llama-3.1-8b-instant")
    ollama_model = config["matching"].get("ollama_model", "qwen3:8b")

    # If config forces Ollama, or Groq already failed this run → go straight to Ollama
    if use_ollama or _groq_failed:
        return _score_via_ollama_safe(job, ollama_model)

    try:
        return _score_via_groq(job, groq_model)
    except Exception as e:
        err = str(e).lower()
        is_quota = any(kw in err for kw in [
            "429", "rate_limit", "rate limit", "quota", "tokens per",
            "requests per", "limit exceeded", "too many requests",
            "connection", "timeout", "503", "502", "500",
        ])
        if is_quota:
            print(f"    Groq unavailable ({type(e).__name__}) — switching to Ollama for rest of run...")
        else:
            print(f"    Groq error ({type(e).__name__}: {str(e)[:80]}) — falling back to Ollama...")
        _groq_failed = True
        return _score_via_ollama_safe(job, ollama_model)
