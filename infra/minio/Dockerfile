# syntax=docker/dockerfile:1.7
# Fixed upstream source + checksum: does not depend on a removed MinIO registry image.
FROM golang:1.23.12-bookworm AS builder
ADD --checksum=sha256:7cc89d321b06b265012fa4f49a4b00a715bab5eef3a157c1d348a93ead51d1d2 https://codeload.github.com/minio/minio/tar.gz/16f8cf1c52f0a77eeb8f7565aaf7f7df12454583 /source.tar.gz
WORKDIR /src
RUN tar -xzf /source.tar.gz --strip-components=1
ENV CGO_ENABLED=0
RUN go build -p 2 -trimpath -ldflags "-s -w -X github.com/minio/minio/cmd.Version=2024-12-18T13:15:44Z -X github.com/minio/minio/cmd.ReleaseTag=SOURCE.2024-12-18T13-15-44Z -X github.com/minio/minio/cmd.CommitID=16f8cf1c52f0a77eeb8f7565aaf7f7df12454583 -X github.com/minio/minio/cmd.ShortCommitID=16f8cf1c52f0 -X github.com/minio/minio/cmd.CopyrightYear=2024" -o /minio .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates curl
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="16f8cf1c52f0a77eeb8f7565aaf7f7df12454583" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.description="Project source build of MinIO; not an upstream release binary"
COPY --from=builder /minio /usr/bin/minio
COPY --from=builder /src/LICENSE /usr/share/minio/LICENSE
# Distribute the corresponding unmodified upstream source with the binary.
COPY --from=builder /source.tar.gz /usr/share/minio/source.tar.gz
ENTRYPOINT ["minio"]
