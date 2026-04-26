FROM python:3.14-slim AS base

WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.14-slim

WORKDIR /app
COPY --from=base /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=base /usr/local/bin /usr/local/bin
COPY --from=base /app /app
COPY main.py ./
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
ENV PYTHONUNBUFFERED=1
USER appuser
CMD ["python", "main.py"]
