FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /tmp/fixture-requirements.txt
RUN python -m pip install \
      --no-cache-dir \
      --only-binary=:all: \
      --require-hashes \
      --requirement /tmp/fixture-requirements.txt

WORKDIR /workspace
ENTRYPOINT ["python", "/workspace/spikes/document-ingestion/fixture_sources/common/generate.py"]
