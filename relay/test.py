"""Historical compatibility entrypoint for the direct Relay test command."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / \"tests.py\"), run_name=\"__main__\")