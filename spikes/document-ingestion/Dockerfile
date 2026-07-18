FROM debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818 AS ocr-model

ARG KOR_TESSDATA_COMMIT=e12c65a915945e4c28e237a9b52bc4a8f39a0cec
ARG KOR_TESSDATA_SHA256=f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl --fail --location --silent --show-error \
      "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/${KOR_TESSDATA_COMMIT}/kor.traineddata" \
      --output /kor.traineddata \
    && echo "${KOR_TESSDATA_SHA256}  /kor.traineddata" | sha256sum --check --strict \
    && rm -rf /var/lib/apt/lists/*

FROM maven:3.9.11-eclipse-temurin-17@sha256:e4a7ace3dc0d645ed97f8d9ad0b0d3f0b14fa8d150138f27f116d7105a639b82 AS hwp-build

WORKDIR /build/hwp-sidecar
COPY spikes/document-ingestion/hwp-sidecar/pom.xml ./
COPY spikes/document-ingestion/hwp-sidecar/src ./src
RUN mvn --batch-mode --no-transfer-progress verify

FROM ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc AS uv

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

ARG TESSERACT_VERSION=5.3.0-2
ARG LEPTONICA_VERSION=1.82.0-3+b3

COPY --from=uv /uv /uvx /bin/
COPY --from=ocr-model /kor.traineddata /usr/share/tesseract-ocr/5/tessdata/kor.traineddata
COPY --from=hwp-build /opt/java/openjdk /opt/java/openjdk
COPY --from=hwp-build /build/hwp-sidecar/target/axit-hwp-sidecar-0.1.0.jar /opt/axit-hwp/sidecar.jar
COPY --from=hwp-build /build/hwp-sidecar/target/dependency /opt/axit-hwp/dependency

ENV PATH="/opt/axit-ingestion/.venv/bin:/opt/java/openjdk/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/axit-ingestion/src \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    UV_LINK_MODE=copy \
    AXIT_HWP_CLASSPATH="/opt/axit-hwp/sidecar.jar:/opt/axit-hwp/dependency/*"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      "liblept5=${LEPTONICA_VERSION}" \
      "libtesseract5=${TESSERACT_VERSION}" \
      "tesseract-ocr=${TESSERACT_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 axit \
    && useradd --uid 10001 --gid axit --no-create-home --shell /usr/sbin/nologin axit \
    && tesseract --version | grep --fixed-strings "tesseract 5.3.0" \
    && test "$(sha256sum /usr/share/tesseract-ocr/5/tessdata/kor.traineddata | cut -d' ' -f1)" = \
      "f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff"

WORKDIR /opt/axit-ingestion
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --only-group ingestion-g0 --no-install-project \
    && rm -rf /root/.cache/uv

COPY spikes/document-ingestion/policy.v1.json ./policy.v1.json
COPY spikes/document-ingestion/src ./src

USER 10001:10001

CMD ["python", "-m", "axit_ingestion_spike.worker"]
