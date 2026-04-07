from models import JobListing, UserProfile

_TEMPLATE = """\
You are a job fit evaluator. You will receive a candidate's background, a set of rules (hard filters), fit criteria (scoring instructions), and a batch of job listings. For each job, either filter it out or score it.

## Candidate background

{background}

## Rules (hard filters)

Apply these rules first. If a job violates any rule, filter it out immediately. Do not score filtered jobs.

{rules}

## Fit criteria (scoring instructions)

For jobs that pass all rules, score them according to these criteria:

{fit_criteria}

## Jobs to evaluate

{jobs}

## Response format

Respond with exactly one block per job, in order. Use this exact format with no deviation:

For a filtered job:
```
JOB_ID: <number>
STATUS: FILTERED
REASON: <one sentence explaining which rule was violated>
```

For a scored job:
```
JOB_ID: <number>
STATUS: SCORED
SCORE: <integer 0-100>
REASONING: <2-3 sentences explaining the score>
HARD_REQUIREMENTS: <bullet list of the job's hard/must-have requirements, e.g. "- 5+ years Python experience | - Bachelor's in CS or related field". Use " | " to separate items. If none stated, write "None listed">
PREFERRED_REQUIREMENTS: <bullet list of the job's preferred/nice-to-have requirements, e.g. "- Experience with Kubernetes | - Familiarity with ML pipelines". Use " | " to separate items. If none stated, write "None listed">
```

Separate each block with a blank line. Do not include any other text before or after the blocks.\
"""


def _format_jobs(jobs: list[JobListing], start_index: int = 0) -> str:
    blocks: list[str] = []
    for i, job in enumerate(jobs):
        job_id = start_index + i
        blocks.append(
            f"### JOB {job_id}\n"
            f"- **Title:** {job.title}\n"
            f"- **Company:** {job.company}\n"
            f"- **Location:** {job.location}\n"
            f"- **Date posted:** {job.date_posted}\n"
            f"- **URL:** {job.url}\n"
            f"- **Description:**\n{job.description}"
        )
    return "\n\n---\n\n".join(blocks)


def build_prompt(profile: UserProfile, jobs: list[JobListing], start_index: int = 0) -> str:
    return _TEMPLATE.format(
        background=profile.background,
        rules=profile.rules,
        fit_criteria=profile.fit_criteria,
        jobs=_format_jobs(jobs, start_index),
    )


def build_continuation_prompt(jobs: list[JobListing], start_index: int) -> str:
    return (
        f"Continue scoring the next batch of jobs using the same rules and criteria.\n\n"
        f"{_format_jobs(jobs, start_index)}"
    )
