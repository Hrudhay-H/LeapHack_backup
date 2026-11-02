#!/bin/sh
# Start the API on $PORT (hosts like Render, Railway and Fly set it; defaults to 8000).
set -e

if [ -z "$AGRISCOUT_SECRET" ]; then
  AGRISCOUT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
  export AGRISCOUT_SECRET
  echo "WARNING: AGRISCOUT_SECRET is not set. Generated a random one; signed-in sessions are lost on restart."
fi
if [ -z "$AGRISCOUT_ADMIN_KEY" ]; then
  echo "WARNING: AGRISCOUT_ADMIN_KEY is not set. Using the public demo key 'demo-admin': anyone can run and reset analyses."
fi
if [ "${AGRISCOUT_DEMO:-1}" = "1" ]; then
  echo "NOTICE: AGRISCOUT_DEMO=1 exposes one-time codes at /api/dev/sms so the demo phone works. Set AGRISCOUT_DEMO=0 for anything real."
fi

# A volume mounted at /app/data starts empty and hides the demo baked into the image: rebuild it (about a minute).
if [ ! -f data/agriscout.db ]; then
  echo "No database found in /app/data; building the demo data..."
  python scripts/bootstrap_demo.py
fi

exec python -m uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
