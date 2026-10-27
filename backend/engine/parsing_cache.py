"""Bounded whole-document cache; immutable bytes/CST stay the authority."""
from __future__ import annotations

from collections import OrderedDict
import copy
from dataclasses import replace
import threading

from .parser import PARSER_VERSION, digest, parse

_cache: OrderedDict = OrderedDict()
_lock = threading.RLock()
_weight = 0
_budget = 64 * 1024 * 1024


def parse_cached(raw: bytes, *, dialect="script", max_bytes=8_000_000, max_tokens=250_000, max_depth=128):
    global _weight
    key = (digest(raw), PARSER_VERSION, dialect, max_bytes, max_tokens, max_depth)
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            document, _ = cached
            _cache.move_to_end(key)
            return replace(document, diagnostics=copy.deepcopy(document.diagnostics))
    document = parse(raw, dialect=dialect, max_bytes=max_bytes, max_tokens=max_tokens, max_depth=max_depth)
    weight = len(raw) * 3 + len(document.tokens) * 384 + len(document.children) * 256
    with _lock:
        if weight <= _budget:
            prior = _cache.pop(key, None)
            if prior:
                _weight -= prior[1]
            while _cache and (_weight + weight > _budget or len(_cache) >= 64):
                _, (_, evicted_weight) = _cache.popitem(last=False)
                _weight -= evicted_weight
            _cache[key] = (document, weight)
            _weight += weight
    return replace(document, diagnostics=copy.deepcopy(document.diagnostics))


def clear_cache():
    global _weight
    with _lock:
        _cache.clear()
        _weight = 0
