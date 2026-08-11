"""
System detection: host CPU/RAM/disk/Docker/OS (diagnostic context,
not tier-scoring - see tiers.py) and real GPU VRAM detection, the one
dimension Anvil's whole tier model actually depends on.

Every GPU check here runs the real vendor query and requires a real
successful result - never just whether a tool binary is on PATH. That
distinction is not academic: researched against a real machine in this
same workspace whose Vulcan detect_gpu() has reported gpu_vendor="amd"
for its entire session history, even though the machine has no AMD
hardware at all (only an Intel iGPU) - rocm-smi happened to be
installed with no working amdgpu driver behind it, and a presence-only
check took that as confirmed AMD. Vulcan's own optional Jellyfin
transcoding tolerates that kind of false positive; Anvil's tier
recommendation is built entirely on a VRAM number, so a false positive
here means confidently recommending a tier the machine cannot deliver
on at all.
"""

import grp
import json
import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from installer.shell import run_ok


_AMD_VENDOR_ID = "0x1002"
_NVIDIA_VENDOR_ID_MARKER = "nvidia"  # nvidia-smi presence is itself the real signal here
_INTEL_ARC_DISCOVERY_PROBE_LIMIT = 8


@dataclass
class GpuInfo:

    vendor: str          # "nvidia" | "amd" | "intel"
    name: str | None
    vram_total_mb: int


@dataclass
class SystemInfo:

    cpu_cores_physical: int | None
    cpu_cores_logical: int | None
    cpu_model: str | None

    ram_total_gb: float

    disk_free_gb: float
    disk_path_checked: str

    gpus: list[GpuInfo]

    docker_installed: bool
    docker_running: bool
    docker_compose_v2: bool

    architecture: str
    os_id: str | None
    os_pretty_name: str | None
    os_is_atomic: bool


def _run(command: list[str], timeout: int = 10) -> subprocess.CompletedProcess | None:

    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None


def detect_nvidia_gpus() -> list[GpuInfo]:
    """
    A real, functional query - if nvidia-smi is on PATH but can't
    actually talk to a GPU (no driver, no card), this returns [],
    the exact class of false positive this module exists to avoid.
    """

    if not shutil.which("nvidia-smi"):
        return []

    proc = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])

    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return []

    gpus = []

    for line in proc.stdout.strip().splitlines():

        parts = [p.strip() for p in line.split(",")]

        if len(parts) != 2:
            continue

        name, vram_str = parts

        try:
            vram_mb = int(vram_str)
        except ValueError:
            continue

        gpus.append(GpuInfo(vendor="nvidia", name=name or None, vram_total_mb=vram_mb))

    return gpus


def detect_amd_gpus() -> list[GpuInfo]:
    """
    Reads the amdgpu kernel driver's own sysfs interface directly
    (mem_info_vram_total, bytes - a real, documented kernel.org
    interface) rather than shelling out to rocm-smi. Deliberately not
    rocm-smi-first: ROCm is frequently absent even on real, working
    AMD GPUs (especially consumer/gaming cards), while this sysfs file
    exists the moment the amdgpu driver itself is loaded - no extra
    tooling required. Confirmed for real that a non-AMD card's device
    directory has no mem_info_* files at all (checked against this
    machine's own Intel iGPU, vendor "0x8086", while researching this).
    """

    gpus = []

    drm_path = Path("/sys/class/drm")

    if not drm_path.is_dir():
        return gpus

    for card_dir in sorted(drm_path.glob("card[0-9]*")):

        device_dir = card_dir / "device"

        try:
            vendor = (device_dir / "vendor").read_text().strip()
        except OSError:
            continue

        if vendor != _AMD_VENDOR_ID:
            continue

        try:
            vram_bytes = int((device_dir / "mem_info_vram_total").read_text().strip())
        except (OSError, ValueError):
            continue

        gpus.append(GpuInfo(vendor="amd", name=None, vram_total_mb=vram_bytes // (1024 * 1024)))

    return gpus


def detect_intel_gpus() -> list[GpuInfo]:
    """
    xpu-smi (Intel's own official tool) only supports discrete Arc/
    Data Center GPUs - confirmed via Intel's real xpumanager docs,
    not assumed. Integrated UHD/Iris graphics has no dedicated VRAM
    pool to query at all (shared system RAM instead), so this
    deliberately never reports anything for integrated-only hosts -
    see tiers.py for why that's a real scoping decision, not a gap.

    Least-verified of the three vendor paths: only the single-device
    query shape (`xpu-smi discovery -d N -j`, real field name
    "Memory Physical Size") was confirmed against real docs - no
    discrete Arc hardware exists anywhere in this project's dev
    environment to verify actual output against. Probes device
    indices one at a time (rather than trusting an unverified
    list-all-devices JSON shape) and fails safe - a shape mismatch or
    missing tool means "no Intel GPUs detected," not a crash.
    """

    if not shutil.which("xpu-smi"):
        return []

    gpus = []

    for index in range(_INTEL_ARC_DISCOVERY_PROBE_LIMIT):

        proc = _run(["xpu-smi", "discovery", "-d", str(index), "-j"])

        if proc is None or proc.returncode != 0 or not proc.stdout.strip():
            break

        try:
            data = json.loads(proc.stdout)
        except ValueError:
            break

        raw_memory = data.get("Memory Physical Size")

        if raw_memory is None:
            continue

        match = re.match(r"([\d.]+)\s*MiB", str(raw_memory))

        if not match:
            continue

        gpus.append(
            GpuInfo(
                vendor="intel",
                name=data.get("Device Name"),
                vram_total_mb=int(float(match.group(1)))
            )
        )

    return gpus


def detect_gpus() -> list[GpuInfo]:
    return detect_nvidia_gpus() + detect_amd_gpus() + detect_intel_gpus()


def detect_primary_gpu(gpus: list[GpuInfo] | None = None) -> GpuInfo | None:
    """
    Largest single card by VRAM, not summed across multiple GPUs - a
    real, deliberate policy decision (see CLAUDE.md): a model has to
    fit in one card's memory to run without multi-GPU-aware sharding,
    which most candidate services don't handle out of the box, so
    summing would recommend tiers the host can't actually satisfy for
    a single model load.
    """

    gpus = detect_gpus() if gpus is None else gpus

    if not gpus:
        return None

    return max(gpus, key=lambda gpu: gpu.vram_total_mb)


def detect_render_group_gid() -> int | None:
    """
    The gid of the host's DRM render-node group - needed alongside
    /dev/dri passthrough for AMD GPU compute, since PUID/PGID alone
    doesn't grant a containerized process access to a device node
    owned by this group. "video" is the fallback name on distros/
    kernels that predate the dedicated "render" group. Mirrors
    Vulcan's identical function (installer/detect.py) exactly - a
    genuinely reusable, domain-agnostic host-detection concern.
    """

    for name in ("render", "video"):

        try:
            return grp.getgrnam(name).gr_gid
        except KeyError:
            continue

    return None


def detect_cpu() -> dict:

    cpu_model = None

    try:

        with open("/proc/cpuinfo") as f:

            for line in f:

                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break

    except OSError:
        cpu_model = None

    try:
        import psutil
        cores_physical = psutil.cpu_count(logical=False)
        cores_logical = psutil.cpu_count(logical=True)
    except ImportError:
        cores_physical = None
        cores_logical = None

    return {
        "cpu_cores_physical": cores_physical,
        "cpu_cores_logical": cores_logical,
        "cpu_model": cpu_model
    }


def detect_memory() -> dict:

    import psutil

    return {"ram_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2)}


def detect_disk(path: str) -> dict:

    try:
        free_bytes = shutil.disk_usage(path).free
    except OSError:
        return {"disk_free_gb": 0.0, "disk_path_checked": path}

    return {"disk_free_gb": round(free_bytes / (1024 ** 3), 2), "disk_path_checked": path}


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """
    A real functional check - attempts an actual TCP connect rather
    than inspecting /proc or shelling out to ss/lsof, so it works the
    same regardless of what's listening (a native systemd service, a
    stray container, anything). Never raises: any socket-level error
    is treated as "can't confirm it's in use," not "in use."
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:

        sock.settimeout(1)

        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def detect_host_ip() -> str | None:
    """
    Best-effort LAN-facing address for the dashboard's links - ported
    from Vulcan's own detect_host_ip(), same reasoning: "localhost" in
    a generated page is only correct when viewed from the machine
    itself, and a GPU-compute box is often a headless server accessed
    from another device's browser. A UDP "connect" sends no actual
    packets (UDP has no handshake); it only asks the kernel's routing
    table which local address it would use to reach that destination,
    which is exactly the address other devices on the same network can
    reach this host at.
    """

    try:

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]

    except OSError:
        return None


def detect_docker() -> dict:

    installed = shutil.which("docker") is not None

    if not installed:
        return {"docker_installed": False, "docker_running": False, "docker_compose_v2": False}

    return {
        "docker_installed": True,
        "docker_running": run_ok(["docker", "info"]),
        "docker_compose_v2": run_ok(["docker", "compose", "version"])
    }


def detect_os_is_atomic() -> bool:
    """
    True on an rpm-ostree-based image (Fedora Silverblue/Kinoite,
    Bazzite, and other Universal Blue derivatives, CoreOS) - a real
    functional signal, not a name guess: /run/ostree-booted is written
    by ostree itself at boot only when the running root is an ostree
    deployment (confirmed against a real Bazzite host while building
    this - present there, absent on a normal mutable Fedora). Docker
    can't be `dnf install`ed on these systems the way install_plan_for's
    existing DOCKER_SCRIPT_DISTROS assume - the base image is read-only,
    packages are layered via `rpm-ostree install` instead, and that
    layering only takes effect after a reboot. shutil.which("rpm-ostree")
    is kept as a fallback for the (currently unobserved) case where the
    marker file itself is missing but the tooling still is - never the
    primary signal, since a tool being on PATH doesn't confirm the
    running root actually is one (the same presence-vs-function
    distinction this module's own docstring already applies to GPU
    detection).
    """

    if Path("/run/ostree-booted").exists():
        return True

    return shutil.which("rpm-ostree") is not None


def detect_os() -> dict:

    os_id = None
    os_pretty_name = None

    try:

        with open("/etc/os-release") as f:

            values = {}

            for line in f:

                line = line.strip()

                if not line or "=" not in line:
                    continue

                key, _, value = line.partition("=")
                values[key] = value.strip('"')

            os_id = values.get("ID")
            os_pretty_name = values.get("PRETTY_NAME")

    except OSError:
        pass

    return {
        "architecture": platform.machine(),
        "os_id": os_id,
        "os_pretty_name": os_pretty_name,
        "os_is_atomic": detect_os_is_atomic()
    }


def detect_system(disk_path: str = ".") -> SystemInfo:
    """
    disk_path defaults to the current directory, not "/" - a real bug
    found live against msi-laptop (an atomic/ostree host): "/" there is
    a tiny, nearly-full composefs root (real free space ~0GB), while
    the actual filesystem `stack/` (GenerationConfig.STACK_DIR, always
    relative to cwd) will be written to - typically under the user's
    home - had hundreds of GB free. Checking "/" reported a misleading
    "Disk free: 0.0GB" right next to "model checkpoints commonly run
    4-140GB+ each," even though nothing was actually wrong. "." is
    correct on every host, atomic or not - it's the one directory this
    project's own writes are guaranteed to land under.
    """

    return SystemInfo(
        **detect_cpu(),
        **detect_memory(),
        **detect_disk(disk_path),
        gpus=detect_gpus(),
        **detect_docker(),
        **detect_os()
    )
