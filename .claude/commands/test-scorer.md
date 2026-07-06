Test the Gemini AI scorer with a sample job to verify it's working correctly.

If the user passes a job title/description in $ARGUMENTS, use that. Otherwise use a default test job.

Run using the Bash tool:

```python
import os, sys
os.chdir(r"c:\Users\ashok\Desktop\JobPilot_AI")
sys.path.insert(0, ".")
from agent.resume_matcher import score_job, load_resume
import yaml

config = yaml.safe_load(open("config.yaml"))
load_resume(config["resume"]["path"])

test_job = {
    "job_id":      "test_001",
    "title":       "Junior React Developer",
    "company":     "TechStartup Pvt Ltd",
    "location":    "Hyderabad",
    "source":      "test",
    "description": "We are looking for a Junior React Developer with 0-1 years of experience. Skills: React.js, Node.js, JavaScript, REST APIs. Freshers welcome. Full-time permanent role.",
}

print("Testing scorer with:", test_job["title"], "@", test_job["company"])
print("Description:", test_job["description"][:100], "...")
print()

result = score_job(test_job)
print(f"Score     : {result.get('score')}/10")
print(f"Reason    : {result.get('reason')}")
print(f"Intern OK : {result.get('internship_friendly')}")
print(f"Exp req   : {result.get('experience_required')}")
```

Execute with the Bash tool. Then explain:
- Which AI provider was used (Gemini/Groq/Ollama)
- Whether the score looks correct for a junior React role
- If there's an error, diagnose it (API key, quota, model name)
