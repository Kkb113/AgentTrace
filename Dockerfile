FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-runtime.txt requirements-build.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-runtime.txt -r requirements-build.txt
COPY pyproject.toml README.md ./
COPY src ./src
COPY packages ./packages
COPY examples/evidence-contract ./examples/evidence-contract
RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation . \
    && useradd --uid 10001 --create-home appuser
USER 10001:10001
ENTRYPOINT ["agenttrace-foundation"]
CMD ["api", "--container"]
