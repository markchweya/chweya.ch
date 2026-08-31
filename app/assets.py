"""A version stamp for the static assets.

Browsers cache stylesheets and scripts hard, and a page that ships new HTML
against a visitor's cached old CSS renders broken in ways no test catches.
Every asset link carries this stamp as a query parameter, so changing a file
changes the URL and the browser fetches the new one. Nobody should need to
know what a hard refresh is.

The stamp is the newest modification time across the served files, read once
per process. The development server restarts on every code change and a
deployment restarts the process, so the stamp is fresh exactly when it needs
to be.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ASSET_DIRS = (Path("app/static"), Path("shared/brand"))


@lru_cache(maxsize=1)
def asset_version() -> str:
    """Return the version stamp for asset URLs."""
    newest = 0
    for root in _ASSET_DIRS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                newest = max(newest, int(path.stat().st_mtime))
    return str(newest)
