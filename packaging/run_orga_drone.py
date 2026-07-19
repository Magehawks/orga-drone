"""Thin PyInstaller entrypoint that keeps the orga_drone package layout intact."""

from orga_drone.__main__ import main

if __name__ == "__main__":
    main()
