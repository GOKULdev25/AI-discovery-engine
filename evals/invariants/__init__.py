"""EV-INV-* — always-on invariants (EVAL.md §7). Importing this package
registers every invariant eval; `scripts/eval.py` imports it unconditionally
on every run.
"""

from evals.invariants import (  # noqa: F401
    test_fabrication_and_taxonomy,
    test_governance,
    test_repo_hygiene,
    test_structural_rules,
)
