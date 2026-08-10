# Thin overlay on bbernhard/signal-cli-rest-api that swaps the bundled
# signal-cli for the reviewed upstream 0.14.6 release.
#
# Originally needed because Signal stopped including `serverGuid` in some
# sealed-sender envelopes; signal-cli <=0.14.4.1 throws
# `getServerGuid(...) must not be null` and DROPS every incoming message
# (sends are unaffected). Fixed upstream in signal-cli 0.14.5
# (AsamK/signal-cli#2059, milestone 0.14.5). bbernhard had not shipped an
# image with the fix, so we drop the official JVM dist in ourselves. Keeping
# the overlay makes the deployed signal-cli version explicit and reproducible.
#
# Remove this image and revert docker-compose to the plain bbernhard tag once
# their :latest (or latest-dev) ships signal-cli >=0.14.5.
FROM rust:1.89-bookworm AS call-tunnel-builder

# signal-cli's calling support deliberately keeps RingRTC in a separate
# process. Pin the tunnel and its RingRTC submodule together: this API is still
# experimental and building an arbitrary moving HEAD would be risky.
ARG SIGNAL_CALL_TUNNEL_COMMIT=69034124090dc6ee9591b0f208f105d034a172c2
RUN apt-get update && apt-get install -y --no-install-recommends \
      clang cmake git libclang-dev libpulse-dev lld ninja-build pkg-config protobuf-compiler \
    && rm -rf /var/lib/apt/lists/* \
    && git clone https://github.com/AsamK/signal-call-tunnel.git /src/signal-call-tunnel \
    && cd /src/signal-call-tunnel \
    && git checkout "${SIGNAL_CALL_TUNNEL_COMMIT}" \
    && git submodule update --init --depth 1 third-party/ringrtc \
    && CC=clang CXX=clang++ RUSTFLAGS="-C linker=clang -C link-arg=-fuse-ld=lld" \
      cargo build --manifest-path signal-call-tunnel/Cargo.toml --release

FROM bbernhard/signal-cli-rest-api:latest-dev

ARG SIGNAL_CLI_VERSION=0.14.6

RUN apt-get update && apt-get install -y --no-install-recommends \
      espeak-ng pulseaudio pulseaudio-utils \
    && rm -rf /var/lib/apt/lists/*

# The official dist carries its own bin/signal-cli launcher with the correct
# version-pinned classpath and bundles the matching libsignal-client jar
# (native .so self-extracts at runtime), so we just unpack it and repoint the
# launcher symlink. Runs on the base image's JDK.
RUN set -eux; \
    curl -fsSL -o /tmp/signal-cli.tar.gz \
      "https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz"; \
    tar -xzf /tmp/signal-cli.tar.gz -C /opt; \
    rm -f /tmp/signal-cli.tar.gz; \
    rm -f /usr/bin/signal-cli; \
    printf '%s\n' '#!/bin/sh' 'export PULSE_SERVER=unix:/run/pulse/native' \
      'exec /opt/signal-cli-'"${SIGNAL_CLI_VERSION}"'/bin/signal-cli "$@"' \
      > /usr/bin/signal-cli; \
    chmod 0755 /usr/bin/signal-cli; \
    signal-cli --version

COPY --from=call-tunnel-builder \
  /src/signal-call-tunnel/signal-call-tunnel/target/release/signal-call-tunnel \
  /usr/local/bin/signal-call-tunnel
COPY call-bridge.py /usr/local/bin/signal-call-bridge
COPY pulse-system.pa /etc/pulse/signal-call.pa
COPY signal-call-bridge.conf /etc/supervisor/conf.d/signal-call-bridge.conf

# Keep the proof-of-concept greeting local to the Lenovo. It remains available
# when the GPU PC and audio-api are offline.
RUN chmod 0755 /usr/local/bin/signal-call-tunnel /usr/local/bin/signal-call-bridge \
    && espeak-ng -w /usr/local/share/signal-call-greeting.wav \
      "Hey Kacper. Signal calling works. Talk to you soon."
