import unittest
from orgbench.statistics import paired_comparison, summarize, holm_adjust


def row(task, success, arch="a"):
    return {"task_id": task, "architecture": arch, "family": "test", "evaluation": {"success": success, "score": float(success)}, "status": "ok", "wall_s": 1}


class StatsTests(unittest.TestCase):
    def test_repetitions_do_not_inflate_task_count(self):
        result = paired_comparison([row("t", True)] * 10, [row("t", False)] * 10)
        self.assertEqual(result["tasks"], 1)
        self.assertEqual(result["p_two_sided"], 1)

    def test_identical_results(self):
        vals = [row(str(i), bool(i % 2)) for i in range(10)]
        comparison = paired_comparison(vals, vals)
        self.assertEqual(comparison["delta"], 0.)
        self.assertEqual(comparison["p_two_sided"], 1.)

    def test_exact_sign_permutation(self):
        result = paired_comparison([row(str(i), True) for i in range(6)], [row(str(i), False) for i in range(6)])
        self.assertEqual(result["p_two_sided"], 2 / 64)

    def test_holm_correction(self):
        values = holm_adjust({"a": {"p_two_sided": .01}, "b": {"p_two_sided": .04}})
        self.assertAlmostEqual(values["a"], .02)
        self.assertAlmostEqual(values["b"], .04)

    def test_never_divide_by_no_success(self):
        result = summarize([row("t", False)])
        self.assertIsNone(result["a"]["tokens_per_success"])


if __name__ == "__main__":
    unittest.main()
