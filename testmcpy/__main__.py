"""Allow `python -m testmcpy` to run the CLI (used by `testmcpy bench`)."""

from testmcpy.cli import app

if __name__ == "__main__":
    app()
