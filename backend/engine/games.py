"""Game boundaries: shared byte preservation, separately scoped semantics."""
from __future__ import annotations

import sys


GAME_PLATFORMS = {"eu5": {"windows"}, "ck3": {"macos", "windows"}}


def target_scope(game_id: str = "eu5", platform: str | None = None) -> tuple[str, str]:
    if not isinstance(game_id, str) or game_id not in GAME_PLATFORMS:
        raise ValueError("Unsupported game identity")
    platform = platform or ("macos" if game_id == "ck3" and sys.platform == "darwin" else "windows")
    if platform not in GAME_PLATFORMS[game_id]:
        raise ValueError("Unsupported target platform for this game")
    return game_id, platform


def classify_for_game(path: str, game_id: str = "eu5") -> dict:
    if game_id == "ck3":
        from .ck3 import classify_ck3
        return classify_ck3(path)
    target_scope(game_id)
    from .formats import classify
    return classify(path)


def classifier_for_game(game_id: str = "eu5"):
    """Pin one schema revision throughout a whole source capture."""
    if game_id == "ck3":
        from .ck3 import classify_ck3, schema_manifest
        schemas = schema_manifest()["schemas"]
        return lambda path: classify_ck3(path, schemas=schemas)
    target_scope(game_id)
    from .formats import classify
    return classify


def analyze_for_game(inputs: list[dict], playset: list[str], *, game_id: str = "eu5",
                     target_platform: str | None = None, profile: dict | None = None,
                     baselines: dict | None = None, package_metadata: list[dict] | None = None) -> dict:
    game_id, platform = target_scope(game_id, target_platform)
    if profile and profile.get("game_id", "eu5") != game_id:
        raise ValueError("Rule profile belongs to a different game")
    if profile and profile.get("target_platform", platform) != platform:
        raise ValueError("Rule profile belongs to a different target platform")
    if game_id == "ck3":
        from .ck3 import analyze_ck3
        return analyze_ck3(inputs, playset, target_platform=platform, package_metadata=package_metadata)
    from .analysis import analyze
    return analyze(inputs, playset, profile=profile, baselines=baselines)


def game_capabilities(game_id: str = "eu5", platform: str | None = None) -> dict:
    game_id, platform = target_scope(game_id, platform)
    return {"game_id": game_id, "target_platform": platform, "inventory": True,
            "advisory_analysis": True, "automatic_repairs": game_id == "eu5",
            "production_rules": 0, "validated_promotion": False,
            "runtime_qualified": False,
            "repair_reason": ("CK3 loading, field readers and complete preservation are not conformed; "
                              "automatic repair staging is unavailable." if game_id == "ck3" else
                              "Only explicit synthetic repair contracts are enabled.")}
