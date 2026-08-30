# Tier-A sandbox runner image (MILESTONE_C_PLAN.md section 4).
# Build once:  docker build -t slice-sandbox:pytest .
FROM python:3.12-slim

RUN pip install --no-cache-dir "pytest>=8"

# no ENTRYPOINT: the sandbox passes an explicit argv (python -m pytest ...)
