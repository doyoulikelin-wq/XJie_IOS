FROM python:3.11.15-slim-bookworm@sha256:28255a3ace7eb4c48bc1b57b90af29e1bc82b4fd6c60614a8e3dce61b87ff941

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

COPY requirements.lock ./

RUN python -m pip install \
    --no-deps \
    --only-binary=:all: \
    --require-hashes \
    --requirement requirements.lock

COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY static ./static
COPY tests ./tests

RUN python -m pip install \
    --no-deps \
    --no-build-isolation \
    --no-index \
    .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
