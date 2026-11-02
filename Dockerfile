# AgriScout API (FastAPI + the analysis pipeline + headless Chromium for PDF reports).
# Build:  docker build -t agriscout-api .
# Run:    docker run -p 8000:8000 -e AGRISCOUT_SECRET=... -e AGRISCOUT_ADMIN_KEY=... \
#                    -e AGRISCOUT_CORS_ORIGINS=https://your-site.vercel.app agriscout-api
# The image bakes in a demo database (synthetic fields + the rice survey-day simulator data from deploy/demo-data),
# so it starts ready. Data written at run time lives on the container filesystem and is lost on restart.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/ml \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

WORKDIR /app
RUN pip install --no-cache-dir uv

# Python dependencies from the lockfile, except PyTorch: the locked build pulls CUDA libraries (several GB) and this
# image has no GPU, so the CPU wheels are installed separately (--index outranks PyPI; --extra-index-url would not).
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-hashes --no-emit-project | grep -viE '^(torch|torchvision|triton|nvidia-|cuda-)' > /tmp/requirements.txt \
 && uv pip install --system --no-cache -r /tmp/requirements.txt \
 && uv pip install --system --no-cache torch torchvision \
        --index https://download.pytorch.org/whl/cpu

# Kannada glyphs for the PDF reports (slim images ship no fonts), then Chromium and its system libraries.
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-noto-core \
 && rm -rf /var/lib/apt/lists/* \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY . .
# Generate the demo (synthetic fields, simulator reference, seeded database and reports). Also downloads the ResNet-18
# weights once so the running container needs no outbound access.
RUN python scripts/bootstrap_demo.py

EXPOSE 8000
ENTRYPOINT ["sh", "scripts/docker-entrypoint.sh"]
