# Third-party components

The root MIT license covers this project's original work. It does not relicense
dependencies, upstream source, model weights, or datasets.

| Material | Source and scope |
| --- | --- |
| Signal bot base | `signal-bot.Dockerfile` fetches the pinned `kbak/uoltz` fork. The source URL and revision are required build inputs. |
| Signal calling | `docker/signal-cli-0145/Dockerfile` fetches signal-cli and signal-call-tunnel, including RingRTC dependencies. |
| Image runtime patch | `patches/sdcpp-qwen-image-rgba.patch` modifies stable-diffusion.cpp; consult the upstream license with the patched source. |
| Search configuration | `searxng-settings.yml` includes settings derived from SearXNG. |
| Historical map data | `plc-watcher/plc_watcher/data/plc_1650.geojson` identifies `aourednik/historical-basemaps` as its source. Consult that dataset's terms before redistribution. |
| Model weights | Repositories and revisions are recorded in the launchers and audio image. Each model has its own license and access requirements. |

Container images and Python packages are identified in Compose files,
Dockerfiles, requirements files, and lockfiles. Preserve their notices when
redistributing them. This inventory is not a dependency license audit.
