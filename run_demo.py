"""Convenience entry point: `python run_demo.py` from anywhere (same as `python -m scripts.demo`)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

from scripts.demo import main  # noqa: E402

if __name__ == "__main__":
    main()
