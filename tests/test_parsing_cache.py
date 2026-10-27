from backend.engine import parsing_cache


def test_cache_key_includes_dialect_limits_and_returns_independent_diagnostics(monkeypatch):
    parsing_cache.clear_cache()
    parse = parsing_cache.parse
    calls = []
    def counted(raw, **kwargs):
        calls.append(kwargs)
        return parse(raw, **kwargs)
    monkeypatch.setattr(parsing_cache, "parse", counted)
    first = parsing_cache.parse_cached(b"x = {")
    first.diagnostics[0]["code"] = "caller_mutation"
    second = parsing_cache.parse_cached(b"x = {")
    assert second.diagnostics[0]["code"] != "caller_mutation"
    assert second.serialize() == b"x = {"
    assert len(calls) == 1
    parsing_cache.parse_cached(b"x = {", dialect="gui")
    parsing_cache.parse_cached(b"x = {", max_depth=2)
    assert len(calls) == 3
    parsing_cache.clear_cache()
