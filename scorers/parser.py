import re

from models import FilteredResult, JobListing, ScoredResult, ScoringError, ScoringResult

_KNOWN_KEYS = {"JOB_ID", "STATUS", "REASON", "REASONING", "SCORE", "REQS_MATCH", "DOMAIN_MATCH", "GAPS", "HARD_REQUIREMENTS", "PREFERRED_REQUIREMENTS"}


def _parse_block(block: str) -> dict[str, str]:
    """Parse a single response block into a key/value dict.

    Handles multi-line values (e.g. REASONING spanning multiple sentences)
    by appending continuation lines to the last known key. Any blank line
    followed by a non-key line is treated as trailing thought text and
    truncated — this prevents LLM thinking/reasoning between fields from
    contaminating the parsed values.
    """
    fields: dict[str, str] = {}
    current_key: str | None = None
    saw_blank = False

    for line in block.splitlines():
        key, sep, value = line.partition(": ")
        if sep and key.strip() in _KNOWN_KEYS:
            current_key = key.strip()
            fields[current_key] = value.strip()
            saw_blank = False
            continue

        stripped = line.strip()

        # Blank line followed by a non-key line = trailing thought text
        if saw_blank and current_key is not None:
            current_key = None
            saw_blank = False
            continue

        if not stripped:
            saw_blank = True
            continue

        if current_key is not None:
            fields[current_key] += " " + stripped

    return fields


def parse_response(response: str, jobs: list[JobListing], start_index: int = 0) -> list[ScoringResult]:
    """Parse Claude's batch response into a list of ScoringResults.

    Results are returned in the same order as the input jobs list.
    Raises ScoringError if the response is malformed or job count doesn't match.
    """
    # Strip code fences and any preamble before the first JOB_ID.
    first_job = re.search(r"^JOB_ID:", response, flags=re.MULTILINE)
    if first_job:
        response = response[first_job.start():]
    response = re.sub(r"```\w*", "", response).strip()

    raw_blocks = re.split(r"(?=^JOB_ID:)", response, flags=re.MULTILINE)
    blocks = [b.strip() for b in raw_blocks if b.strip()]

    expected_ids = set(start_index + i for i in range(len(jobs)))
    results: dict[int, ScoringResult] = {}

    for block in blocks:
        fields = _parse_block(block)

        try:
            job_id = int(fields["JOB_ID"])
            status = fields["STATUS"]
        except KeyError as e:
            raise ScoringError(
                f"Missing required field {e} in block:\n{block}",
                raw_response=response,
            ) from e

        if status == "FILTERED":
            try:
                results[job_id] = FilteredResult(reason=fields["REASON"])
            except KeyError as e:
                raise ScoringError(
                    f"Missing required field {e} in FILTERED block:\n{block}",
                    raw_response=response,
                ) from e
        elif status == "SCORED":
            try:
                results[job_id] = ScoredResult(
                    score=int(fields["SCORE"]),
                    requirements_match=int(fields.get("REQS_MATCH", "0")),
                    domain_match=int(fields.get("DOMAIN_MATCH", "0")),
                    reasoning=fields["REASONING"],
                    gaps=fields.get("GAPS", "No significant gaps identified"),
                    hard_requirements=fields.get("HARD_REQUIREMENTS", "None listed"),
                    preferred_requirements=fields.get("PREFERRED_REQUIREMENTS", "None listed"),
                )
            except KeyError as e:
                raise ScoringError(
                    f"Missing required field {e} in SCORED block:\n{block}",
                    raw_response=response,
                ) from e
        else:
            raise ScoringError(
                f"Unknown STATUS '{status}' in block:\n{block}",
                raw_response=response,
            )

    missing = expected_ids - set(results.keys())
    if missing:
        raise ScoringError(
            f"Missing results for job IDs: {sorted(missing)}",
            raw_response=response,
        )

    return [results[start_index + i] for i in range(len(jobs))]
