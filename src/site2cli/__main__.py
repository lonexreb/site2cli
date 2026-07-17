"""Allow running as ``python -m site2cli``."""

from site2cli.cli import app

if __name__ == "__main__":
    app(prog_name="site2cli")
