import json

from quantaalpha.factors.regulator.subtree_blacklist import SubtreeBlacklist


def test_subtree_blacklist_loads_and_dedups_patterns(tmp_path):
    path = tmp_path / "blacklist.json"
    path.write_text(
        json.dumps(
            [
                "$close",
                "TS_MEAN($close, 5)",
                "TS_MEAN($close,5)",
                {"expr": "delay($close, 1)", "label": "bad_delay"},
            ]
        ),
        encoding="utf-8",
    )

    blacklist = SubtreeBlacklist(str(path), min_nodes=2, max_patterns=100)

    # "$close" has only one node and should be filtered out.
    assert blacklist.size == 3


def test_subtree_blacklist_matches_subtree_in_larger_expression(tmp_path):
    path = tmp_path / "blacklist.json"
    path.write_text(
        json.dumps(
            {
                "patterns": [
                    {"expr": "delay($close, 1)", "label": "bad_delay"},
                ]
            }
        ),
        encoding="utf-8",
    )

    blacklist = SubtreeBlacklist(str(path), min_nodes=1, max_patterns=100)
    match = blacklist.match("rank(delay($close, 1) - $volume)")

    assert match is not None
    assert match.pattern_label == "bad_delay"
