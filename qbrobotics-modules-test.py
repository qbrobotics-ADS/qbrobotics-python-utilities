######################################################################################
######################################################################################
"""Compatibility entry point; importing this file never opens serial ports."""

from qbrobotics_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
