FROM searxng/searxng@sha256:1ef964f6dcc811a60e01049717b6e526b25a1c52935350143f04e0ae291b3dbd
COPY --chmod=755 searxng-entrypoint.sh /usr/local/bin/local-searxng-entrypoint.sh
ARG STACK_REVISION=dev
LABEL org.opencontainers.image.revision=$STACK_REVISION
