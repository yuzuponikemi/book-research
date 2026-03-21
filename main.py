"""Entry point shim — delegates to cogito orchestrator.

Usage: python main.py [same flags as cogito.orchestrator]
"""
from cogito.orchestrator.cli import main

if __name__ == "__main__":
    main()
