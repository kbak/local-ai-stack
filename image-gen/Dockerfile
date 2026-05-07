FROM nvidia/cuda:12.8.1-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        wget \
        unzip \
        libgl1 \
        libglib2.0-0 \
        ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# .NET 8 SDK — SwarmUI is a C# app and needs the SDK at runtime to build the
# server binary on first launch. Microsoft's apt feed for noble (Ubuntu 24.04).
RUN wget -q https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb -O /tmp/ms.deb && \
    dpkg -i /tmp/ms.deb && \
    rm /tmp/ms.deb && \
    apt-get update && \
    apt-get install -y --no-install-recommends dotnet-sdk-8.0 && \
    rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python

# Clone SwarmUI. Pinning a tag rather than tracking main so rebuilds are
# reproducible. Bump SWARMUI_REV to upgrade.
ARG SWARMUI_REV=0.9.8-Beta
WORKDIR /opt
RUN git clone https://github.com/mcmonkeyprojects/SwarmUI.git swarmui && \
    cd swarmui && \
    git checkout ${SWARMUI_REV}

WORKDIR /opt/swarmui

# SwarmUI's launch-linux.sh starts the server and never exits, so we can't
# call it during build. Instead, do just the dotnet restore + build here so
# first container start skips the ~90s C# compile.
RUN dotnet build src/SwarmUI.csproj --configuration Release

# SwarmUI auto-installs ComfyUI as its backend on first launch. Force its
# Python venv to use the cu128 PyTorch wheels needed for Blackwell.
ENV SWARMUI_TORCH_INDEX=https://download.pytorch.org/whl/cu128

EXPOSE 7801

COPY image-gen/entrypoint.sh /opt/swarmui/entrypoint.sh
COPY image-gen/Backends.fds /opt/swarmui/Data/Backends.fds
RUN chmod +x /opt/swarmui/entrypoint.sh

ENTRYPOINT ["/opt/swarmui/entrypoint.sh"]
CMD ["--host", "0.0.0.0", "--port", "7801", "--launch_mode", "none"]
