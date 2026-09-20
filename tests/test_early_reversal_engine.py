import unittest
import early_reversal_engine as engine


class EarlyReversalEngineSmokeTests(unittest.TestCase):
    def test_module_imports_and_exposes_engine(self):
        self.assertTrue(callable(engine.evaluate_setup))
        self.assertTrue(callable(engine.infer_direction))
        self.assertTrue(callable(engine.atr))


if __name__ == "__main__":
    unittest.main(verbosity=2)
