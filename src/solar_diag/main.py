"""Vstupní bod. Naslouchá na 8080, do baterie sahá jen v 192.168.99.0/24."""

from __future__ import annotations

import logging
import os
import sys


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    import uvicorn

    host = os.environ.get("HTTP_HOST", "0.0.0.0")
    port = int(os.environ.get("HTTP_PORT", "8080"))
    uvicorn.run("solar_diag.api:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
