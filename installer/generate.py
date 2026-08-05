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

from installer.detect import GpuInfo, detect_render_group_gid
from installer.tiers import TIERS, TierDefinition, enabled_service_keys


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STACK_DIR = Path("stack")
STATE_FILENAME = ".anvil-state.json"


@dataclass
class GenerationConfig:

    tier: TierDefinition
    puid: int
    pgid: int
    gpu: GpuInfo | None = None
    enabled_optional: set[str] = field(default_factory=set)


def default_puid_pgid() -> tuple[int, int]:
    return os.getuid(), os.getgid()


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


def render_compose(config: GenerationConfig) -> str:

    template = _jinja_env().get_template("docker-compose.yml.j2")
    gpu_vendor = config.gpu.vendor if config.gpu else None

    return template.render(
        enabled=enabled_service_keys(config.tier, config.gpu, config.enabled_optional),
        gpu_vendor=gpu_vendor,
        puid=config.puid,
        pgid=config.pgid,
        render_gid=detect_render_group_gid() if gpu_vendor == "amd" else None
    )


def write_stack(config: GenerationConfig, output_dir: Path = STACK_DIR) -> dict:

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    compose_path = output_dir / "docker-compose.yml"
    compose_path.write_text(render_compose(config))
    save_state(config, output_dir)

    enabled = enabled_service_keys(config.tier, config.gpu, config.enabled_optional)

    for key in enabled:
        (output_dir / "data" / key).mkdir(parents=True, exist_ok=True)

    warnings = []

    heavy_wants_comfyui = (
        config.tier.name == "heavy"
        and "comfyui" in config.enabled_optional
        and "comfyui" not in enabled
    )

    if heavy_wants_comfyui:

        warnings.append(
            "ComfyUI was requested but skipped: the only real, verified images for it "
            "(mmartial/comfyui-nvidia-docker for NVIDIA, corundex/comfyui-rocm for AMD) "
            f"support NVIDIA and AMD only, and this host's detected GPU is "
            f"{config.gpu.vendor if config.gpu else 'none'}. An Intel Arc-compatible image "
            "hasn't been researched yet - see CLAUDE.md's still-open questions."
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

    if "open-webui" in enabled and "comfyui" in enabled:

        warnings.append(
            "Open WebUI and ComfyUI don't wire themselves together automatically - in "
            "Open WebUI, go to Admin Panel > Settings > Images, enable Image Generation, "
            "set the engine to ComfyUI, and point it at http://comfyui:8188, then click "
            "Verify Connection."
        )

    return {
        "success": True,
        "compose_path": str(compose_path),
        "warnings": warnings
    }
