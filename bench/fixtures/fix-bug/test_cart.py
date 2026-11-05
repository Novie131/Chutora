import unittest

from cart import total


class CartTest(unittest.TestCase):
    def test_no_code(self):
        self.assertEqual(total([(100, 2), (50, 1)]), 250)

    def test_percent_discount(self):
        self.assertEqual(total([(100, 2), (50, 1)], "SAVE10"), 225)

    def test_half(self):
        self.assertEqual(total([(30, 1)], "HALF"), 15)

    def test_unknown_code(self):
        self.assertEqual(total([(30, 1)], "NOPE"), 30)


if __name__ == "__main__":
    unittest.main()
