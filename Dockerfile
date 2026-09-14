FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
RUN adduser --disabled-password --gecos "" appuser

FROM base AS deps
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

FROM deps AS test
COPY . .
RUN python -m pytest

FROM base AS runtime
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY app ./app
COPY data/transactions.csv data/merchants.csv ./data/
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=2s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
