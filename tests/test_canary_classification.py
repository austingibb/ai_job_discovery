"""Unit tests for the live canary's cross-preset classification logic.

Pure and fast: these exercise _aggregate() directly with synthetic PresetResults,
covering the routing cases that are awkward or expensive to trigger against a live
browser (single-preset maintenance, layer-4 selector drift, mixed-layer failures).
"""

from canaries.live_canary import _aggregate
from canaries.result import Classification, Layer, PresetResult


def _healthy(name="p_ok", jobs=40):
    return PresetResult(name=name, url="u", healthy=True, job_count=jobs)


def _failed(name, layer, classification):
    return PresetResult(
        name=name, url="u", healthy=False, failed_layer=layer, classification=classification
    )


def test_all_healthy_is_healthy():
    result = _aggregate([_healthy("a"), _healthy("b")], commit="abc", scorer_ran=True)
    assert result.classification is Classification.HEALTHY
    assert result.healthy is True
    assert result.escalate is False
    assert result.failed_presets == []


def test_all_failed_same_layer_is_systemic():
    presets = [
        _failed("a", Layer.LISTINGS_PARSE, Classification.SCRAPER_SELECTOR_DRIFT),
        _failed("b", Layer.LISTINGS_PARSE, Classification.SCRAPER_SELECTOR_DRIFT),
    ]
    result = _aggregate(presets, commit="abc", scorer_ran=True)
    assert result.classification is Classification.SCRAPER_SELECTOR_DRIFT
    assert result.escalate is True
    assert set(result.failed_presets) == {"a", "b"}


def test_one_failed_others_healthy_is_maintenance():
    presets = [
        _healthy("good", jobs=40),
        _failed("bad", Layer.RESULTS_CONTAINER, Classification.URL_OR_STRUCTURE_DRIFT),
    ]
    result = _aggregate(presets, commit="abc", scorer_ran=True)
    assert result.classification is Classification.CANARY_MAINTENANCE
    assert result.healthy is False
    assert result.escalate is True
    assert result.failed_presets == ["bad"]


def test_all_failed_mixed_layers_keys_on_earliest():
    presets = [
        _failed("a", Layer.LISTINGS_PARSE, Classification.SCRAPER_SELECTOR_DRIFT),
        _failed("b", Layer.RESULTS_CONTAINER, Classification.URL_OR_STRUCTURE_DRIFT),
    ]
    result = _aggregate(presets, commit="abc", scorer_ran=True)
    # RESULTS_CONTAINER is the earlier (more fundamental) layer.
    assert result.classification is Classification.URL_OR_STRUCTURE_DRIFT
    assert result.escalate is True


def test_healthy_but_zero_jobs_does_not_count_as_healthy_cross_check():
    # A "healthy" preset that somehow returned 0 jobs must not satisfy the
    # "others returned healthy results with jobs" maintenance branch.
    presets = [
        _healthy("good_but_empty", jobs=0),
        _failed("bad", Layer.RESULTS_CONTAINER, Classification.URL_OR_STRUCTURE_DRIFT),
    ]
    result = _aggregate(presets, commit="abc", scorer_ran=True)
    assert result.classification is not Classification.CANARY_MAINTENANCE
