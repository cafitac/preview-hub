FROM docker:27-cli AS docker
# Kubernetes runner: kubectl applies environments, buildctl sends builds to the cluster's buildkitd
FROM registry.k8s.io/kubectl:v1.35.0 AS kubectl
FROM moby/buildkit:v0.25.1 AS buildkit
FROM python:3.12-slim
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
COPY --from=docker /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
COPY --from=kubectl /bin/kubectl /usr/local/bin/kubectl
COPY --from=buildkit /usr/bin/buildctl /usr/local/bin/buildctl
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home phub && mkdir /state /src && chown phub:phub /state /src
WORKDIR /app
COPY pyproject.toml README.md ./
COPY preview_hub ./preview_hub
COPY schemas ./schemas
RUN pip install --no-cache-dir .
USER phub
CMD ["phub", "serve"]
