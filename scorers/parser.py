import re

from models import FilteredResult, JobListing, ScoredResult, ScoringError, ScoringResult

_KNOWN_KEYS = {"JOB_ID", "STATUS", "REASON", "REASONING", "SCORE", "HARD_REQUIREMENTS", "PREFERRED_REQUIREMENTS"}


def _parse_block(block: str) -> dict[str, str]:
    """Parse a single response block into a key/value dict.

    Handles multi-line values (e.g. REASONING spanning multiple sentences)
    by appending continuation lines to the last known key.
    """
    fields: dict[str, str] = {}
    current_key: str | None = None

    for line in block.splitlines():
        key, sep, value = line.partition(": ")
        if sep and key.strip() in _KNOWN_KEYS:
            current_key = key.strip()
            fields[current_key] = value.strip()
        elif current_key is not None and line.strip():
            fields[current_key] += " " + line.strip()

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

    if len(blocks) != len(jobs):
        raise ScoringError(
            f"Expected {len(jobs)} result blocks, got {len(blocks)}",
            raw_response=response,
        )

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
                    reasoning=fields["REASONING"],
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

    if len(results) != len(jobs):
        raise ScoringError(
            "Duplicate JOB_IDs in response",
            raw_response=response,
        )

    return [results[start_index + i] for i in range(len(jobs))]
