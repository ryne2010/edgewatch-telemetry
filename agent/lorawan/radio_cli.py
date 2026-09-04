"""Command-line entrypoint for the fail-closed radio ingress supervisor."""

from .radio import main


if __name__ == "__main__":
    raise SystemExit(main())
