FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Preserve the deployed source revision when refreshing dependencies/base images.
ARG UOLTZ_REV=45d402cc7b154d54d7c752f93827a3dd576d0e28
RUN git clone https://github.com/kbak/uoltz.git /uoltz && \
    git -C /uoltz checkout "${UOLTZ_REV}"
COPY services/signal-bot/patches/constraints.txt services/signal-bot/requirements.txt /tmp/
RUN pip install --no-cache-dir -c /tmp/constraints.txt \
    -r /uoltz/app/requirements.txt -r /tmp/requirements.txt

# The installed package stays in the image; development mounts use PYTHONPATH.
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps /shared/

RUN cp -r /uoltz/app/. .
COPY services/signal-bot/patches/image_tools.py services/signal-bot/patches/operation_context.py /app/
COPY services/signal-bot/patches/ /tmp/bot-patches/
RUN python /tmp/bot-patches/apply_patches.py

# Keep executable skills outside /app/data, which is a persistent state volume.
COPY services/signal-bot/skills/ /app/custom_skills/

ARG STACK_REVISION=dev
LABEL org.opencontainers.image.revision=$STACK_REVISION
CMD ["python", "bot.py"]
