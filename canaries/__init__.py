"""Canaries for the ai_job_discovery pipeline.

Two canaries live here:

- mock_pipeline: a pure, browser-free check of the core pipeline (scrape ->
  prefilter -> score -> report) using the mock plugin and mock scorer. It is
  exercised by tests/test_mock_canary.py.
- live_canary: a layered precondition chain run against broad "software / all
  USA" preset URLs. The first failing layer determines the classification, and
  the canary emits a structured CanaryResult for a downstream triage process to
  consume.

The canaries do detection and classification only. They never edit scraper code.
"""
