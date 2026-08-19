"""
Jinja2 rendering: takes the chosen tier + configuration answers and
renders templates/docker-compose.yml.j2 into a real stack/docker-
compose.yml. write_stack() does real file I/O but never prompts or
confirms - that's the CLI layer's job, the same split Vulcan keeps
between generate.py and cli.py.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from installer.detect import GpuInfo, detect_host_ip, detect_render_group_gid, port_in_use
from installer.secrets import N8N_CREDENTIALS_FILENAME, load_or_create_n8n_credentials
from installer.tiers import TIERS, TierDefinition, enabled_service_keys
from installer.vulcan_integration import (
    build_homepage_tiles,
    check_vulcan_port_conflicts,
    merge_into_vulcan_homepage,
)


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STACK_DIR = Path("stack")
STATE_FILENAME = ".anvil-state.json"

# The one port per service the compose template ever publishes -
# mirrors the hardcoded "ports:" values in docker-compose.yml.j2,
# same convention as the vendor-specific knowledge already hardcoded
# below for the NVIDIA Container Toolkit warning.
SERVICE_PORTS = {
    "ollama": 11434, "open-webui": 3000, "comfyui": 8188, "invokeai": 9090,
    # Real defaults, sourced from ODS's own already-running compose
    # definitions rather than guessed - qdrant/tts/n8n keep their
    # images' own default ports unremapped; whisper's real container
    # default (8000) is remapped to 9000 on the host, matching ODS's
    # own choice, likely to avoid colliding with common dev-tool ports.
    "qdrant": 6333, "embeddings": 8090, "whisper": 9000, "tts": 8880, "n8n": 5678
}

# The dashboard isn't a tiers.py ServiceDefinition (not user-choosable,
# not tier-gated) - it's always rendered, so its port gets its own
# constant and its own conflict check rather than living in
# SERVICE_PORTS, which is only ever walked over the `enabled` set.
DASHBOARD_PORT = 8080


@dataclass
class GenerationConfig:

    tier: TierDefinition
    puid: int
    pgid: int
    gpu: GpuInfo | None = None
    enabled_optional: set[str] = field(default_factory=set)
    port_overrides: dict[str, int] = field(default_factory=dict)
    # Set by the CLI/menu layer after find_vulcan_stack() + user
    # confirmation - None means "no co-located Vulcan install, or the
    # user didn't want to integrate with it," Anvil's own standalone
    # dashboard is unaffected either way.
    vulcan_stack_dir: Path | None = None


def default_puid_pgid() -> tuple[int, int]:
    return os.getuid(), os.getgid()


def resolve_ports(config: GenerationConfig) -> dict[str, int]:
    """
    SERVICE_PORTS is the single real registry of every service's
    default host port (used for port-conflict checks and the post-start
    summary) - port remapping reuses it rather than inventing a second
    table that could drift out of sync. config.port_overrides wins
    per-key when present; a conflict-remediation flow (CLI or whiptail menu) is the
    only real caller that ever sets it.
    """

    all_ports = {**SERVICE_PORTS, "dashboard": DASHBOARD_PORT}
    return {**all_ports, **config.port_overrides}


def render_stack_summary(config: GenerationConfig, host_ip: str | None) -> str:
    """
    Real per-service URLs for the currently-generated stack - shared
    by the CLI's own post-start printout and `anvil urls` (which
    installer/menu.sh's whiptail Setup Complete screen calls), so the
    two can never drift into showing different addresses. Falls back
    to "localhost" only when host_ip detection itself failed, not as
    a default choice - a host reached over SSH with no local browser
    needs the real LAN-facing address, the same reasoning
    detect_host_ip() and the generated dashboard HTML already apply.
    """

    host = host_ip or "localhost"
    resolved = resolve_ports(config)

    lines = [
        f"  Dashboard:    http://{host}:{resolved['dashboard']}",
        f"  Ollama API:   http://{host}:{resolved['ollama']}",
        f"  Open WebUI:   http://{host}:{resolved['open-webui']}",
    ]

    if "comfyui" in config.enabled_optional:
        lines.append(f"  ComfyUI:      http://{host}:{resolved['comfyui']}")

    if "invokeai" in config.enabled_optional:
        lines.append(f"  InvokeAI:     http://{host}:{resolved['invokeai']}")

    if "qdrant" in config.enabled_optional:
        lines.append(f"  Qdrant:       http://{host}:{resolved['qdrant']}/dashboard")

    if "whisper" in config.enabled_optional:
        lines.append(f"  Whisper STT:  http://{host}:{resolved['whisper']}")

    if "tts" in config.enabled_optional:
        lines.append(f"  Kokoro TTS:   http://{host}:{resolved['tts']}")

    if "n8n" in config.enabled_optional:
        lines.append(f"  n8n:          http://{host}:{resolved['n8n']}")

    return "\n".join(lines)


def save_state(config: GenerationConfig, output_dir: Path) -> None:

    state = {
        "tier": config.tier.name,
        "puid": config.puid,
        "pgid": config.pgid,
        "gpu_vendor": config.gpu.vendor if config.gpu else None,
        "enabled_optional": sorted(config.enabled_optional),
        "generated_at": datetime.now(dt_timezone.utc).isoformat()
    }

    (output_dir / STATE_FILENAME).write_text(json.dumps(state, indent=2))


def load_previous_state(output_dir: Path) -> dict | None:
    """
    Never raises - missing file, corrupt JSON, or an unknown tier name
    all just mean "no usable previous state."
    """

    try:

        state = json.loads((output_dir / STATE_FILENAME).read_text())
        assert state["tier"] in TIERS
        return state

    except (OSError, json.JSONDecodeError, KeyError, AssertionError):
        return None


def _jinja_env() -> Environment:

    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False
    )


def render_compose(
    config: GenerationConfig,
    resolved_ports: dict[str, int] | None = None,
    n8n_credentials: dict | None = None
) -> str:

    template = _jinja_env().get_template("docker-compose.yml.j2")
    gpu_vendor = config.gpu.vendor if config.gpu else None

    if resolved_ports is None:
        resolved_ports = resolve_ports(config)

    return template.render(
        enabled=enabled_service_keys(config.tier, config.gpu, config.enabled_optional),
        gpu_vendor=gpu_vendor,
        puid=config.puid,
        pgid=config.pgid,
        render_gid=detect_render_group_gid() if gpu_vendor == "amd" else None,
        ports=resolved_ports,
        n8n_email=n8n_credentials["email"] if n8n_credentials else None,
        n8n_password=n8n_credentials["password"] if n8n_credentials else None
    )


def render_dashboard(config: GenerationConfig) -> str:

    template = _jinja_env().get_template("dashboard.html.j2")

    return template.render(
        enabled=enabled_service_keys(config.tier, config.gpu, config.enabled_optional),
        host=detect_host_ip() or "localhost"
    )


def write_stack(config: GenerationConfig, output_dir: Path = STACK_DIR) -> dict:

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_ports = resolve_ports(config)
    enabled = enabled_service_keys(config.tier, config.gpu, config.enabled_optional)

    n8n_credentials_are_new = "n8n" in enabled and not (output_dir / N8N_CREDENTIALS_FILENAME).exists()
    n8n_credentials = load_or_create_n8n_credentials(output_dir) if "n8n" in enabled else None

    compose_path = output_dir / "docker-compose.yml"
    compose_path.write_text(render_compose(config, resolved_ports, n8n_credentials))
    save_state(config, output_dir)

    for key in enabled:
        (output_dir / "data" / key).mkdir(parents=True, exist_ok=True)

    dashboard_dir = output_dir / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    (dashboard_dir / "index.html").write_text(render_dashboard(config))

    warnings = []

    heavy_wants_comfyui = (
        config.tier.name == "heavy"
        and "comfyui" in config.enabled_optional
        and "comfyui" not in enabled
    )

    if heavy_wants_comfyui:

        # Defensive, not expected to fire in practice as of this writing
        # - all three vendors detect.py can ever detect (nvidia/amd/intel)
        # have a real, verified ComfyUI image now. Kept for the case
        # config.gpu is None (requested without a GPU at all) or a future
        # vendor gets detection support before an image is researched.
        warnings.append(
            "ComfyUI was requested but skipped: no real, verified ComfyUI image "
            f"supports this host's detected GPU ({config.gpu.vendor if config.gpu else 'none'})."
        )

    heavy_wants_invokeai = (
        config.tier.name == "heavy"
        and "invokeai" in config.enabled_optional
        and "invokeai" not in enabled
    )

    if heavy_wants_invokeai:

        # A real, currently-live gap, not purely defensive the way the
        # ComfyUI version above now is: InvokeAI's official image has no
        # Intel Arc support at all (confirmed - only a non-Docker
        # community workaround exists, invoke-ai/InvokeAI itself never
        # shipped an XPU build), so a Heavy-tier Intel host requesting it
        # hits this today, not just in a hypothetical future-vendor case.
        warnings.append(
            "InvokeAI was requested but skipped: no real InvokeAI image supports this "
            f"host's detected GPU ({config.gpu.vendor if config.gpu else 'none'}) - only "
            "NVIDIA and AMD have official images as of this writing, Intel Arc has none."
        )

    if config.gpu and config.gpu.vendor == "nvidia" and enabled:

        # A real, separate gap from GPU presence itself: nvidia-smi
        # (what detection above already confirmed working) and the
        # NVIDIA Container Toolkit (the separate OCI runtime hook
        # Docker needs to actually pass a GPU into a container) are
        # independently installed - detecting the GPU proves nothing
        # about whether the toolkit is present. AMD/Intel need no
        # equivalent warning: /dev/kfd and /dev/dri passthrough are
        # plain Docker device mounts, no special container runtime
        # required, and detect_amd_gpus()/detect_intel_gpus() already
        # only succeed when the real kernel driver is loaded - unlike
        # nvidia-smi, which works standalone regardless of whether the
        # separate container-toolkit integration exists.
        warnings.append(
            "GPU passthrough requires the NVIDIA Container Toolkit to be installed and "
            "registered with Docker on this host, separately from the NVIDIA driver "
            "detection above already confirmed - Anvil doesn't install it automatically. "
            "Install guide: "
            "https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
        )

    if config.gpu and config.gpu.vendor == "amd" and "comfyui" in enabled:

        # A real, vendor-specific gap, confirmed by reading each image's
        # own docs/entrypoint rather than assumed: NVIDIA's
        # (mmartial/comfyui-nvidia-docker) and Intel's
        # (yanwk/comfyui-boot) images both bundle ComfyUI-Manager
        # already; AMD's (corundex/comfyui-rocm) doesn't. A bare git
        # clone into the custom_nodes volume alone wouldn't be enough
        # to fix it, either - confirmed by reading the image's real
        # startup.sh, which starts ComfyUI directly with no step that
        # installs a custom node's own requirements.txt, so Manager
        # would very likely fail to import without the pip install
        # below. Not automated here: doing this from write_stack()
        # would need git and network access at generate time (neither
        # assumed anywhere else in this codebase) to reliably clone
        # into place, and even then the pip install step still has to
        # run inside the container after it exists - safer and more
        # honest to hand the user the exact real commands.
        warnings.append(
            "This AMD ComfyUI image doesn't include ComfyUI-Manager (NVIDIA and Intel "
            "Arc's images both do) - add it once after your first start:\n"
            "    git clone https://github.com/Comfy-Org/ComfyUI-Manager "
            f"{output_dir}/data/comfyui/custom_nodes/ComfyUI-Manager\n"
            "    docker compose exec comfyui pip install -r "
            "/workspace/ComfyUI/custom_nodes/ComfyUI-Manager/requirements.txt\n"
            "    docker compose restart comfyui"
        )

    if config.gpu and config.gpu.vendor == "amd" and "invokeai" in enabled:

        # A real, InvokeAI-specific gap, not shared with Ollama/ComfyUI's
        # AMD blocks: InvokeAI's own official compose file (confirmed by
        # fetching it directly, not an AI-summarized version - a prior
        # summarized fetch of Decluttarr's config got a similar detail
        # wrong, see CLAUDE.md) uses `runtime: amd` + AMD_VISIBLE_DEVICES,
        # AMD's own separate Container Toolkit-registered Docker runtime -
        # not the plain /dev/kfd + /dev/dri device passthrough Ollama and
        # ComfyUI's AMD images use here, which needs no special runtime
        # registration at all. Detecting the GPU (this project's
        # sysfs/rocm-smi-based detect_amd_gpus()) proves nothing about
        # whether that separate runtime is registered with Docker.
        warnings.append(
            "InvokeAI's AMD image needs the AMD Container Toolkit registered with "
            "Docker on this host (a separate \"amd\" runtime - not the plain device "
            "passthrough Ollama/ComfyUI use here) - Anvil doesn't install or register "
            "it automatically. Install guide: "
            "https://instinct.docs.amd.com/projects/container-toolkit/en/latest/"
        )

    if "open-webui" in enabled and "comfyui" in enabled:

        warnings.append(
            "Open WebUI and ComfyUI don't wire themselves together automatically - in "
            "Open WebUI, go to Admin Panel > Settings > Images, enable Image Generation, "
            "set the engine to ComfyUI, and point it at http://comfyui:8188, then click "
            "Verify Connection."
        )

    if "open-webui" in enabled and "qdrant" in enabled and "embeddings" in enabled:

        # Same "explain rather than silently automate" precedent as the
        # ComfyUI wiring warning above - Open WebUI's RAG settings are
        # admin-panel configuration, not compose-level, same as ComfyUI.
        warnings.append(
            "Qdrant and the embeddings service don't wire themselves into Open WebUI's "
            "document retrieval automatically - in Open WebUI, go to Admin Panel > "
            "Settings > Documents, set Vector Database to Qdrant "
            "(http://qdrant:6333), and set the Embedding Model Engine to OpenAI with "
            "Base URL http://embeddings:80/v1 (no API key required)."
        )

    if "open-webui" in enabled and "whisper" in enabled:

        warnings.append(
            "Whisper doesn't wire itself into Open WebUI's voice input automatically - "
            "in Open WebUI, go to Admin Panel > Settings > Audio, set Speech-to-Text "
            "Engine to OpenAI, and set the API Base URL to http://whisper:8000/v1."
        )

    if "open-webui" in enabled and "tts" in enabled:

        warnings.append(
            "Kokoro doesn't wire itself into Open WebUI's voice output automatically - "
            "in Open WebUI, go to Admin Panel > Settings > Audio, set Text-to-Speech "
            "Engine to OpenAI, and set the API Base URL to http://tts:8880/v1."
        )

    if n8n_credentials_are_new:

        # The only place this password is ever shown - credentials are
        # write-once (load_or_create_n8n_credentials()), so a later
        # regenerate reuses the same login rather than locking the user
        # out of an n8n instance they've already set workflows up in.
        warnings.append(
            "n8n admin login (shown only once - stored at "
            f"{output_dir}/{N8N_CREDENTIALS_FILENAME} if you need it again):\n"
            f"    Email:    {n8n_credentials['email']}\n"
            f"    Password: {n8n_credentials['password']}"
        )

    for key in enabled:

        port = resolved_ports.get(key)

        if port is not None and port_in_use(port):

            if key == "ollama":

                # Worth a richer warning than the other two: unlike a
                # plain port squat, an existing listener on 11434 is
                # commonly a native Ollama install (this exact scenario
                # is real, not hypothetical - found on the machine this
                # project develops on, a systemd-managed install with a
                # real 4.9GB model already downloaded). That native
                # store lives under /usr/share/ollama/.ollama, owned and
                # locked down (mode 0700) by the dedicated "ollama"
                # system user - not something this container can safely
                # reuse without either loosening those permissions or
                # running the container as that system UID, so Anvil
                # doesn't attempt to share it. The honest trade-off is
                # surfaced here instead of hidden: stop the native
                # service first to free the port and let this container
                # own it (models will download again into this stack's
                # own data/ollama), or leave it running and expect this
                # container's Ollama to fail to bind.
                warnings.append(
                    "Port 11434 is already in use, commonly a sign of an existing "
                    "native Ollama install (check with: systemctl status ollama) - this "
                    "stack's ollama container will fail to bind that port until it's "
                    "freed. A native install's models can't be safely reused here (its "
                    "storage is typically locked down to a dedicated system user), so "
                    "stopping the native service (sudo systemctl stop ollama) means this "
                    "container will re-download any models you already have."
                )

            else:

                warnings.append(
                    f"Port {port} is already in use by something else on this host - "
                    f"the {key} container will fail to bind it until that's freed."
                )

    if port_in_use(resolved_ports.get("dashboard", DASHBOARD_PORT)):

        warnings.append(
            f"Port {DASHBOARD_PORT} is already in use by something else on this host - "
            "the dashboard container will fail to bind it until that's freed."
        )

    if config.vulcan_stack_dir is not None:

        enabled_ports = {key: resolved_ports[key] for key in enabled if key in resolved_ports}
        warnings.extend(check_vulcan_port_conflicts(enabled_ports, config.vulcan_stack_dir))

        host = detect_host_ip() or "localhost"
        tiles = build_homepage_tiles(enabled, resolved_ports, host)
        merged = merge_into_vulcan_homepage(config.vulcan_stack_dir, tiles)

        if merged:
            warnings.append(
                f"Added a Homepage section at {config.vulcan_stack_dir}/config/homepage/"
                "services.yaml for your enabled services - only that one section is "
                "ever touched, nothing else in the file."
            )
        elif tiles:
            warnings.append(
                f"Found a Vulcan stack at {config.vulcan_stack_dir}, but it doesn't have "
                "Homepage enabled - nothing to add a section to."
            )

    return {
        "success": True,
        "compose_path": str(compose_path),
        "warnings": warnings
    }
