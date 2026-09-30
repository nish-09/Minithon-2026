"""Start a throw-away embedded PostgreSQL (dev/test only) and print its SQLAlchemy URL.

    python scripts/pg_test_server.py            # prints URL, keeps running until Ctrl+C
    NEXA_DATABASE_URL=<url> pytest              # run the suite against real PostgreSQL

Requires the optional dev package `pixeltable-pgserver` (pip install pixeltable-pgserver "psycopg[binary]").
"""
import sys
import tempfile
import time
from pathlib import Path

import pixeltable_pgserver as pgserver

data = Path(tempfile.gettempdir()) / "nexa-pgdata"
srv = pgserver.get_server(data, cleanup_mode=None)
uri = srv.get_uri()  # postgresql://postgres:@/postgres?host=...
# SQLAlchemy wants the psycopg3 dialect explicitly
url = uri.replace("postgresql://", "postgresql+psycopg://", 1)
print(url, flush=True)
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    sys.exit(0)
