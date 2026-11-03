import unittest

from orgbench.task_suite_v6 import generate_independent_suite, ordered_digest


class SamplerTests(unittest.TestCase):
    def test_reproducible_unique_tasks_and_seeds(self):
        first = generate_independent_suite("dev", 3, 71)
        self.assertEqual(first, generate_independent_suite("dev", 3, 71))
        self.assertEqual(len(first), 9)
        self.assertEqual(len({t["id"] for t in first}), 9)
        self.assertEqual(len({t["metadata"]["task_seed"] for t in first}), 9)
        for task in first:
            self.assertEqual(len(task["public"]["examples"]), 3)
            self.assertEqual(len(task["private"]["cases"]), 30)

    def test_prefix_stability_and_split_separation(self):
        short = generate_independent_suite("dev", 1, 72)
        long = generate_independent_suite("dev", 4, 72)
        self.assertEqual(short, [t for t in long if t["id"].endswith("_000")])
        other = generate_independent_suite("holdout", 1, 72)
        self.assertFalse({t["metadata"]["task_seed"] for t in short} &
                         {t["metadata"]["task_seed"] for t in other})

    def test_invalid_counts(self):
        for count in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                generate_independent_suite(per_family=count)

    def test_semantically_relevant_mapping_order_is_fingerprinted(self):
        first = {"patch": {"a": 1, "b": 2}}
        reordered = {"patch": {"b": 2, "a": 1}}
        self.assertEqual(first, reordered)
        self.assertNotEqual(ordered_digest(first), ordered_digest(reordered))


if __name__ == "__main__":
    unittest.main()
