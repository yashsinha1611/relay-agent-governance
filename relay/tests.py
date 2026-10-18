"""Direct Relay test entrypoint: runs the suite, nonzero on failure."""

import unittest


if __name__ == "__main__":
    from pathlib import Path
    root = Path(__file__).resolve().parent
    result = unittest.main(module=None, argv=["relay-tests", "discover", "-s", str(root / "tests"), "-t", str(root.parent)], exit=False).result
    raise SystemExit(0 if result.wasSuccessful() else 1)