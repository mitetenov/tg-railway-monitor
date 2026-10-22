# syntax=docker/dockerfile:1
ARG GO_VERSION=1.27.3

# Build natively and cross-compile; releases do not require QEMU.
FROM --platform=$BUILDPLATFORM golang:${GO_VERSION}-alpine AS build
WORKDIR /src
ENV CGO_ENABLED=0

# No third-party modules. Keep the manifest before source for stable caching.
COPY go.mod ./
RUN go mod download

# Static runtime assets change independently of the application binary.
RUN mkdir -p /runtime/app/data /runtime/tmp /runtime/etc/ssl/certs \
    && chmod 1777 /runtime/tmp \
    && chown 1000:1000 /runtime/app/data \
    && cp /etc/ssl/certs/ca-certificates.crt /runtime/etc/ssl/certs/

COPY *.go stations.json ./
COPY locales/ ./locales/
ARG TARGETOS=linux
ARG TARGETARCH
RUN --mount=type=cache,target=/root/.cache/go-build \
    GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -buildvcs=false \
    -ldflags='-s -w' -o /out/ticket-monitor .

# Version stamping is isolated from compilation and its cache.
FROM build AS metadata
COPY version.txt /out/version.txt
ARG VERSION
RUN if [ -n "$VERSION" ]; then printf '%s\n' "$VERSION" > /out/version.txt; fi

# Only CA roots, writable directories, and the static executable ship.
# Locales, station names, and timezone data are embedded in the executable.
FROM scratch AS runtime
COPY --from=build /runtime/ /
COPY --from=build /out/ticket-monitor /app/ticket-monitor
WORKDIR /app
USER 1000:1000
ENV DATA_DIR=/app/data
ENTRYPOINT ["/app/ticket-monitor"]

# Version changes invalidate only this tiny final layer and image metadata.
COPY --from=metadata /out/version.txt /app/version.txt
ARG VERSION=0.1.0
LABEL org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.title="tg-ticket-monitor" \
      org.opencontainers.image.description="Telegram bot for monitoring train ticket availability" \
      org.opencontainers.image.source="https://github.com/mitetenov/tg-railway-monitor"
