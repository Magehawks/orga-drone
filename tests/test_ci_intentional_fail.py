"""Temporary intentional failure to verify CI fails closed. Do not merge."""

def test_intentional_ci_failure() -> None:
    assert False, "intentional failure for CI verification"
