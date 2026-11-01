#!/usr/bin/env python3
"""Run the AILv1 test suite with the standard library only: python3 verify_ail.py"""
import sys
import unittest

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
