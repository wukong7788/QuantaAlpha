from quantaalpha.factors.regulator import CONSISTENCY_CHECKER_AVAILABLE


def test_consistency_checker_available_is_bool():
    assert isinstance(CONSISTENCY_CHECKER_AVAILABLE, bool)

