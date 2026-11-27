from amo_core.context_budget import compact_parts


def test_dynamic_facts_are_prioritized_over_static_rules():
    parts = ["固定规则" * 4, "【正在】在家休息", "【天气】晴，22度"]
    result = compact_parts(parts, max_chars=20)
    assert result == ["【正在】在家休息", "【天气】晴，22度"]


def test_duplicate_parts_are_removed_after_whitespace_normalization():
    result = compact_parts(["记住 这件事", "记住\n这件事", "另一条"])
    assert result == ["记住 这件事", "另一条"]


def test_truncation_never_exceeds_the_character_budget():
    result = compact_parts(["a" * 150, "b" * 200], max_chars=300)
    assert len("\n".join(result)) <= 300
    assert result[-1].endswith("…")
