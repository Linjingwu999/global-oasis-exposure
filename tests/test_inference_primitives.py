"""Unit tests for the two inference primitives that ship without an estimand.

``tests/verify_current_minimum.py`` recomputes all 31 point estimands, which
exercises ``estimands.py`` end to end. It does not touch ``multiple_testing``
or ``bootstrap.stable_seed``, because neither takes part in a point estimate:
the FDR q-values and the 95% intervals are read from the locked ledger rather
than re-derived (see ``docs/reproduction_workflow.md`` section 6). v1.0.0 covered
both in ``tests/test_locked_outputs.py``, which was dropped when the release was
rebuilt around the 3,437-oasis population; these are the checks worth keeping.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

# Import the way scripts/reproduce.py does, so this test exercises the real
# package layout. Loading the files individually with importlib would break on
# the relative imports inside bootstrap.py and would not prove the shipped
# entry point can reach them.
sys.path.insert(0, str(ROOT / "code"))

from core import bootstrap, multiple_testing  # noqa: E402


class BenjaminiHochbergTests(unittest.TestCase):
    def test_worked_example(self) -> None:
        """Three equal p-values adjust to the same q, as in the v1.0.0 test."""
        observed = multiple_testing.benjamini_hochberg(pd.Series([0.01, 0.02, 0.03]))
        np.testing.assert_allclose(observed.to_numpy(), [0.03, 0.03, 0.03])

    def test_monotone_and_bounded(self) -> None:
        """q-values never decrease with p and never exceed 1."""
        p_values = pd.Series([0.001, 0.008, 0.039, 0.041, 0.042, 0.6, 0.99])
        q_values = multiple_testing.benjamini_hochberg(p_values).to_numpy()
        self.assertTrue(np.all(np.diff(q_values) >= -1e-12), q_values)
        self.assertTrue(np.all(q_values <= 1.0), q_values)
        self.assertTrue(np.all(q_values >= p_values.to_numpy() - 1e-12), q_values)

    def test_index_is_preserved_not_reordered(self) -> None:
        """Sorting happens internally; the caller's index must survive it.

        The implementation sorts, adjusts, then writes back by label. A switch
        to positional assignment would silently pair each q-value with the
        wrong estimand, which no downstream check would catch.
        """
        p_values = pd.Series([0.30, 0.01, 0.20], index=["c", "a", "b"])
        q_values = multiple_testing.benjamini_hochberg(p_values)
        self.assertEqual(list(q_values.index), ["c", "a", "b"])
        # p = 0.01 sits at position 1, not 0. Positional write-back would give
        # it the q belonging to p = 0.30.
        self.assertAlmostEqual(q_values["a"], 0.03)
        self.assertLess(q_values["a"], q_values["b"])
        # b and c tie: 0.20 * 3/2 and 0.30 * 3/3 are both 0.30.
        self.assertLessEqual(q_values["b"], q_values["c"])
        self.assertAlmostEqual(q_values["c"], 0.30)

    def test_missing_values_stay_missing(self) -> None:
        """A non-numeric or absent p-value yields NaN, never a silent 0 or 1."""
        q_values = multiple_testing.benjamini_hochberg(
            pd.Series([0.01, np.nan, "not a number", 0.04])
        )
        self.assertTrue(np.isnan(q_values.iloc[1]))
        self.assertTrue(np.isnan(q_values.iloc[2]))
        self.assertFalse(np.isnan(q_values.iloc[0]))
        self.assertTrue(multiple_testing.benjamini_hochberg(pd.Series([], dtype=float)).empty)


class StableSeedTests(unittest.TestCase):
    def test_deterministic_across_calls(self) -> None:
        self.assertEqual(
            bootstrap.stable_seed("primary:example:500"),
            bootstrap.stable_seed("primary:example:500"),
        )

    def test_scale_changes_the_seed(self) -> None:
        """Different run keys must not collide, or two scales share a stream."""
        self.assertNotEqual(
            bootstrap.stable_seed("primary:example:500"),
            bootstrap.stable_seed("primary:example:250"),
        )

    def test_base_seed_participates(self) -> None:
        self.assertNotEqual(
            bootstrap.stable_seed("primary:example:500"),
            bootstrap.stable_seed("primary:example:500", base_seed=1),
        )

    def test_pinned_value(self) -> None:
        """Pin one seed. The locked intervals are only reproducible while the
        key-to-seed mapping is unchanged, so a refactor that alters it must
        fail here rather than quietly produce a different replicate stream."""
        self.assertEqual(
            bootstrap.stable_seed("primary:example:500"),
            2329867101271430082,
        )

    def test_fits_numpy_seed_range(self) -> None:
        seed = bootstrap.stable_seed("primary:example:500")
        self.assertGreaterEqual(seed, 0)
        self.assertLess(seed, 2**64)
        np.random.default_rng(seed)  # must not raise


if __name__ == "__main__":
    unittest.main()
