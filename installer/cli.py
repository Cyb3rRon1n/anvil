import getpass
import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from installer import __version__
from installer.detect import detect_docker, detect_host_ip, detect_primary_gpu, detect_system
from installer.docker_setup import (
    add_user_to_docker_group,
    check_docker_ready,
    ensure_compose_v2,
    install_docker,
    install_plan_for,
    run_docker_command,
    start_docker_service,
)
from installer.generate import (
    STACK_DIR,
    GenerationConfig,
    default_puid_pgid,
    load_previous_state,
    resolve_ports,
    write_stack,
)
from installer.post_install import remove_orphaned_containers
from installer.preflight import check_ports_available, format_port_conflicts
from installer.tiers import TIERS, recommend_tier


app = typer.Typer(
    name="anvil",
    help="A GPU-compute creativity forge - inspects your GPU's real VRAM and builds a tailored local AI/creative stack."
)

console = Console()

MENU_SH_PATH = Path(__file__).parent / "menu.sh"


@app.command()
def version():
    console.print(f"[bold red]Anvil[/bold red] version {__version__}")


def _shell_quote(value: str) -> str:
    """Single-quoted, safe to eval - escapes any embedded single quotes."""

    return "'" + value.replace("'", "'\\''") + "'"


@app.command(name="detect")
def detect_shell():
    """
    Print real detected system state as KEY=VALUE lines, eval-able from
    bash (`eval "$(anvil detect)"`). Exists so installer/menu.sh (the
    whiptail front end) can show real specs and a real tier
    recommendation before asking the user anything, without duplicating
    any detection logic here.
    """

    previous = load_previous_state(STACK_DIR)

    info = detect_system()
    gpu = detect_primary_gpu(info.gpus)
    recommendation = recommend_tier(gpu)

    compose_path = STACK_DIR / "docker-compose.yml"
    stack_exists = compose_path.exists()

    default_puid, default_pgid = default_puid_pgid()

    gpu_vendor = ""
    gpu_vram_mb = 0
    gpu_name = ""
    if gpu:
        gpu_vendor = gpu.vendor
        gpu_vram_mb = gpu.vram_total_mb
        gpu_name = gpu.name or ""

    fields = {
        "CPU_CORES_LOGICAL": info.cpu_cores_logical or 0,
        "CPU_MODEL": _shell_quote(info.cpu_model or "unknown"),
        "RAM_TOTAL_GB": info.ram_total_gb,
        "DISK_FREE_GB": info.disk_free_gb,
        "GPU_VENDOR": _shell_quote(gpu_vendor),
        "GPU_VRAM_MB": gpu_vram_mb,
        "GPU_NAME": _shell_quote(gpu_name),
        "DOCKER_INSTALLED": "true" if info.docker_installed else "false",
        "DOCKER_RUNNING": "true" if info.docker_running else "false",
        "DOCKER_COMPOSE_V2": "true" if info.docker_compose_v2 else "false",
        "OS_ID": _shell_quote(info.os_id or "unknown"),
        "OS_PRETTY_NAME": _shell_quote(info.os_pretty_name or "unknown"),
        "OS_IS_ATOMIC": "true" if info.os_is_atomic else "false",
        "RECOMMENDED_TIER": recommendation.tier.name if recommendation.tier else "",
        "RECOMMENDED_TIER_EXPLANATION": _shell_quote(recommendation.explanation),
        "STACK_EXISTS": "true" if stack_exists else "false",
        "DEFAULT_PUID": default_puid,
        "DEFAULT_PGID": default_pgid,
        "PREVIOUS_TIER": previous["tier"] if previous else "",
        "PREVIOUS_PUID": previous["puid"] if previous else "",
        "PREVIOUS_PGID": previous["pgid"] if previous else "",
        "PREVIOUS_ENABLED_OPTIONAL": ",".join(previous["enabled_optional"]) if previous else "",
        "PREVIOUS_GPU_VENDOR": (previous.get("gpu_vendor") or "") if previous else "",
        "PREVIOUS_GENERATED_AT": (previous.get("generated_at") or "") if previous else "",
    }

    for key, value in fields.items():
        print(f"{key}={value}")


def _launch_menu() -> int:
    """
    Launches the whiptail Main Menu (installer/menu.sh) as a real
    subprocess. Every choice it gathers is handed back to this same
    `anvil` binary as a --non-interactive --yes invocation (see
    menu.sh itself), so this function owns no interactive logic of its
    own, only the handoff.
    """

    menu_env = os.environ.copy()
    menu_env["ANVIL_BIN"] = str(Path(sys.executable).parent / "anvil")

    result = subprocess.run(["bash", str(MENU_SH_PATH)], env=menu_env)
    return result.returncode


def _ensure_docker_ready(info, non_interactive: bool, yes: bool) -> tuple:
    """
    Mirrors Vulcan's own _ensure_docker_ready() shape:
    detect, then offer to fix each of the three real readiness gaps
    (not installed / not running / no compose v2) behind a confirm,
    rather than just printing a link and exiting - the gap a real run
    against a real Bazzite (atomic OS) GPU host exposed directly.
    Returns (info, group_just_added) - group_just_added tells the
    caller whether the final `docker compose up` needs the sg-based
    group-refresh workaround (see run_docker_command) because this
    same run just added the user to the docker group.
    """

    group_just_added = False

    if info.docker_installed and info.docker_running and info.docker_compose_v2:
        console.print("[green]Docker is ready.[/green]")
        return info, group_just_added

    if not info.docker_installed:

        plan = install_plan_for(info.os_id, info.os_is_atomic)

        if plan is None:

            console.print(
                f"[red]No known automatic install method for '{info.os_id}'. "
                "Install Docker manually: https://docs.docker.com/engine/install/[/red]"
            )
            raise typer.Exit(code=1)

        console.print(f"Docker isn't installed. Anvil can install it via: {plan['description']}")

        proceed = yes if non_interactive else typer.confirm("Install Docker now?", default=True)

        if not proceed:
            console.print("[red]Docker is required. Install it manually and re-run.[/red]")
            raise typer.Exit(code=1)

        result = install_docker(info.os_id, info.os_is_atomic)

        if not result["success"]:
            console.print(f"[red]Docker install failed: {result['error']}[/red]")
            raise typer.Exit(code=1)

        if result["needs_reboot"]:

            console.print(
                "[yellow]Docker was layered onto this system via rpm-ostree (this is an "
                "atomic/immutable OS - Bazzite, Silverblue, Kinoite, or similar). That "
                "only takes effect after a reboot.[/yellow]\n\n"
                "Reboot this machine now, then re-run `anvil` - it will detect Docker is "
                "installed and pick up from there (starting the service, adding your "
                "user to the docker group):\n"
                "  sudo systemctl reboot"
            )
            raise typer.Exit(code=0)

        start_docker_service()

        group_result = add_user_to_docker_group(getpass.getuser())

        if not group_result["success"]:
            console.print(f"[red]Failed to add your user to the docker group: {group_result['error']}[/red]")
            raise typer.Exit(code=1)

        ensure_compose_v2(info.os_id)
        group_just_added = True

        console.print(
            "[yellow]Docker was just installed and your user was added to the docker "
            "group - if starting the stack below fails with a permission error, log out "
            "and back in and re-run anvil.[/yellow]"
        )

    elif not info.docker_running:

        console.print("Docker is installed but not running.")

        proceed = yes if non_interactive else typer.confirm(
            "Start the Docker service now?", default=True
        )

        if not proceed:
            console.print("[red]Docker must be running. Start it manually and re-run.[/red]")
            raise typer.Exit(code=1)

        result = start_docker_service()

        if not result["success"]:
            console.print(f"[red]Failed to start Docker: {result['error']}[/red]")
            raise typer.Exit(code=1)

        # Real gap found live against msi-laptop: Docker installed by
        # a *previous* run (the atomic-OS reboot-split case) never got
        # its user added to the docker group, since that only happened
        # alongside a fresh install above. The daemon starting cleanly
        # doesn't mean this user can reach it - /var/run/docker.sock is
        # root:docker, confirmed for real. add_user_to_docker_group()
        # is safe to call even if the user already is a member.
        group_result = add_user_to_docker_group(getpass.getuser())

        if not group_result["success"]:
            console.print(f"[red]Failed to add your user to the docker group: {group_result['error']}[/red]")
            raise typer.Exit(code=1)

        group_just_added = True

    elif not info.docker_compose_v2:

        console.print("Docker Compose v2 isn't available.")

        proceed = yes if non_interactive else typer.confirm(
            "Install Docker Compose v2 now?", default=True
        )

        if not proceed:
            console.print(
                "[red]Docker Compose v2 is required. Install it manually and re-run.[/red]"
            )
            raise typer.Exit(code=1)

        result = ensure_compose_v2(info.os_id)

        if not result["success"]:
            console.print(f"[red]{result['error']}[/red]")
            raise typer.Exit(code=1)

    docker_state = detect_docker()
    info.docker_installed = docker_state["docker_installed"]
    info.docker_running = docker_state["docker_running"]
    info.docker_compose_v2 = docker_state["docker_compose_v2"]

    if group_just_added:

        # A plain detect_docker() re-check right after adding this
        # process's own user to the docker group would still see the
        # stale group list inherited at this session's login - see
        # check_docker_ready()'s own docstring for the real failure
        # this fixes, confirmed live rather than assumed.
        readiness = check_docker_ready(use_group_workaround=True)
        info.docker_running = readiness["docker_running"]
        info.docker_compose_v2 = readiness["docker_compose_v2"]

    if not (info.docker_installed and info.docker_running and info.docker_compose_v2):

        console.print(
            "[red]Docker still isn't ready after the assisted install - check the output "
            "above.[/red]"
        )
        raise typer.Exit(code=1)

    console.print("[green]Docker is ready.[/green]")

    return info, group_just_added


def _resolve_port_conflicts(config: GenerationConfig, result: dict, non_interactive: bool) -> dict:
    """
    Ported from Vulcan's own port-conflict remediation. Turns "here's
    what's wrong" into "let's fix it and retry" for the two real cases
    the diagnosis already distinguishes - your own orphaned containers
    (safe to clean up automatically) and an unrelated service (needs a
    different port, not a cleanup). A third, genuinely unresolvable
    case (a non-Docker/native service holding the port) still ends in
    a clean refusal; this only replaces the *dead end*, not the
    boundary.

    Loops rather than handling one pass, since fixing one conflict can
    surface another (e.g. a typed-in port that happens to collide with
    a second still-conflicting service) - each pass regenerates via
    write_stack() and re-checks for real before declaring victory or
    asking again.
    """

    while True:

        port_check = check_ports_available(result["compose_path"])

        if port_check["available"]:
            return result

        console.print("[red]Can't start - port(s) already in use:[/red]")
        console.print(format_port_conflicts(port_check))

        if non_interactive:
            console.print(
                "[red]Free them, then run this when you're ready:\n"
                f"  docker compose -f {result['compose_path']} up -d[/red]"
            )
            raise typer.Exit(code=1)

        remappable = resolve_ports(config)
        resolved_any = False

        own_orphan_cleaned = False

        for port in port_check["conflicts"]:

            service_key = port_check["port_services"].get(port)

            if port_check["own_orphan"].get(port):

                if own_orphan_cleaned:
                    resolved_any = True
                    continue

                if typer.confirm(
                    f"Port {port} (and any other ports below from the same stack) is "
                    "held by your own orphaned containers from a previous stack. Stop "
                    "and remove them now?",
                    default=True
                ):

                    cleanup = remove_orphaned_containers(STACK_DIR.name)

                    if cleanup["success"]:
                        resolved_any = True
                        own_orphan_cleaned = True
                    else:
                        console.print(f"[red]{cleanup['error']}[/red]")

                continue

            if service_key is None or service_key not in remappable:

                console.print(
                    f"[yellow]Port {port} can't be remapped automatically - free it "
                    "manually and retry.[/yellow]"
                )
                continue

            new_port_str = typer.prompt(
                f"Enter a new host port for {service_key} (currently {port}), or "
                "press Enter to leave it and resolve manually",
                default="",
                show_default=False
            )

            if not new_port_str:
                continue

            try:
                new_port = int(new_port_str)
            except ValueError:
                console.print("[red]Not a valid port number - skipped.[/red]")
                continue

            if new_port in remappable.values():
                console.print(
                    f"[red]Port {new_port} is already used by another service in "
                    "this stack - skipped.[/red]"
                )
                continue

            config.port_overrides[service_key] = new_port
            resolved_any = True

        if not resolved_any:
            console.print(
                "[red]Free the port(s) above, then run this when you're ready:\n"
                f"  docker compose -f {result['compose_path']} up -d[/red]"
            )
            raise typer.Exit(code=1)

        result = write_stack(config)
        console.print(f"[green]Stack regenerated at {result['compose_path']}[/green]")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    tier: str | None = typer.Option(None, "--tier", help="Tier to use (light/medium/heavy)"),
    comfyui: bool | None = typer.Option(
        None, "--comfyui/--no-comfyui",
        help="Include ComfyUI (image generation) - only offered at Heavy tier on NVIDIA GPUs"
    ),
    invokeai: bool | None = typer.Option(
        None, "--invokeai/--no-invokeai",
        help="Include InvokeAI (turnkey image generation) - only offered at Heavy tier on NVIDIA/AMD GPUs"
    ),
    puid: int | None = typer.Option(None, "--puid"),
    pgid: int | None = typer.Option(None, "--pgid"),
    start: bool | None = typer.Option(None, "--start/--no-start"),
    plain: bool = typer.Option(False, "--plain", help="Use the plain CLI prompts instead of the whiptail menu")
):
    if ctx.invoked_subcommand is not None:
        return

    if not non_interactive and not plain:

        raise typer.Exit(code=_launch_menu())

    run_install(non_interactive, yes, tier, comfyui, invokeai, puid, pgid, start)


def run_install(
    non_interactive: bool,
    yes: bool,
    tier_override: str | None,
    comfyui: bool | None,
    invokeai: bool | None,
    puid: int | None,
    pgid: int | None,
    start: bool | None
):

    if non_interactive and not yes:
        console.print("[red]--yes is required alongside --non-interactive.[/red]")
        raise typer.Exit(code=1)

    console.print("[bold]Detecting your system...[/bold]")

    info = detect_system()
    gpus = info.gpus
    gpu = detect_primary_gpu(gpus)

    console.print(
        f"  CPU: {info.cpu_cores_logical} logical cores ({info.cpu_model or 'unknown'})\n"
        f"  RAM: {info.ram_total_gb}GB total\n"
        f"  Disk free: {info.disk_free_gb}GB (model checkpoints commonly run 4-140GB+ each)\n"
        f"  OS: {info.os_pretty_name or info.os_id or 'unknown'} ({info.architecture})"
    )

    if not gpus:
        console.print("  GPU: none with real dedicated VRAM detected")
    else:
        for candidate in gpus:
            console.print(
                f"  GPU: {candidate.vendor.upper()}"
                f"{f' {candidate.name}' if candidate.name else ''} - "
                f"{candidate.vram_total_mb / 1024:.1f}GB VRAM"
            )
        if len(gpus) > 1:
            console.print(
                f"  (multiple GPUs detected - sizing against the largest, "
                f"{gpu.vendor.upper()} at {gpu.vram_total_mb / 1024:.1f}GB)"
            )

    info, group_just_added = _ensure_docker_ready(info, non_interactive, yes)

    recommendation = recommend_tier(gpu)

    if recommendation.tier is None:

        console.print(f"\n[yellow]{recommendation.explanation}[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]{recommendation.explanation}[/bold]")

    previous = load_previous_state(STACK_DIR)
    default_tier_name = previous["tier"] if previous else recommendation.tier.name

    if tier_override is not None:
        chosen_tier_name = tier_override
    elif non_interactive:
        chosen_tier_name = default_tier_name
    else:

        console.print(
            "\nOllama runs the local LLM and manages its own model downloads. "
            "Open WebUI is the chat interface in front of it - no setup needed beyond "
            "picking a model on first visit."
        )

        chosen_tier_name = typer.prompt(
            "Which tier? (light/medium/heavy)", default=default_tier_name
        )

    if chosen_tier_name not in TIERS:
        console.print(f"[red]'{chosen_tier_name}' must be light, medium, or heavy.[/red]")
        raise typer.Exit(code=1)

    chosen_tier = TIERS[chosen_tier_name]
    enabled_optional = set()

    if chosen_tier_name == "heavy":

        # All three real vendors detect.py can detect (NVIDIA, AMD,
        # Intel Arc) have a real, verified ComfyUI image now -
        # mmartial/comfyui-nvidia-docker, corundex/comfyui-rocm,
        # yanwk/comfyui-boot:xpu respectively.
        comfyui_supported = gpu is not None and gpu.vendor in ("nvidia", "amd", "intel")

        # Never defaults to "wanted" on hardware that can't actually
        # render it - a real bug caught by testing: an earlier version
        # of this default was a blind True, which meant a fresh
        # non-interactive run on unsupported hardware silently
        # requested ComfyUI anyway, relying on write_stack()'s vendor
        # gate to quietly drop it and warn rather than the CLI's own
        # default being honest up front.
        comfyui_default = (
            "comfyui" in previous["enabled_optional"] if previous else comfyui_supported
        ) and comfyui_supported

        if comfyui is None:

            if non_interactive:
                enable_comfyui = comfyui_default
            elif comfyui_supported:

                models_path = (
                    "stack/data/comfyui/basedir/models" if gpu.vendor == "nvidia"
                    else "stack/data/comfyui/models"
                )

                enable_comfyui = typer.confirm(
                    "Enable ComfyUI (image generation)? Model checkpoints have to be placed "
                    f"manually under {models_path} after first start - Ollama pulls its own "
                    "models automatically, ComfyUI does not.",
                    default=comfyui_default
                )

            else:
                enable_comfyui = False

        else:
            enable_comfyui = comfyui

        if enable_comfyui:
            enabled_optional.add("comfyui")

        # Only NVIDIA and AMD have a real, official InvokeAI image -
        # confirmed via invoke-ai/InvokeAI's own docker/ directory.
        # Intel Arc has none (only a non-Docker community workaround
        # exists), a real, currently-live gap, not a future-vendor
        # hypothetical the way ComfyUI's equivalent check above now is.
        invokeai_supported = gpu is not None and gpu.vendor in ("nvidia", "amd")

        invokeai_default = (
            "invokeai" in previous["enabled_optional"] if previous else invokeai_supported
        ) and invokeai_supported

        if invokeai is None:

            if non_interactive:
                enable_invokeai = invokeai_default
            elif invokeai_supported:

                enable_invokeai = typer.confirm(
                    "Enable InvokeAI (turnkey image generation)? A simpler alternative to "
                    "ComfyUI's node-based UI - model checkpoints can be downloaded straight "
                    "from InvokeAI's own built-in Model Manager (HuggingFace repo IDs, "
                    "curated starter models), no manual file placement needed.",
                    default=invokeai_default
                )

            else:
                enable_invokeai = False

        else:
            enable_invokeai = invokeai

        if enable_invokeai:
            enabled_optional.add("invokeai")

    default_puid, default_pgid = default_puid_pgid()

    if previous:
        default_puid = previous["puid"]
        default_pgid = previous["pgid"]

    if puid is None:
        final_puid = default_puid if non_interactive else typer.prompt("PUID", default=default_puid, type=int)
    else:
        final_puid = puid

    if pgid is None:
        final_pgid = default_pgid if non_interactive else typer.prompt("PGID", default=default_pgid, type=int)
    else:
        final_pgid = pgid

    config = GenerationConfig(
        tier=chosen_tier,
        puid=final_puid,
        pgid=final_pgid,
        gpu=gpu,
        enabled_optional=enabled_optional
    )

    console.print("\n[bold]Review[/bold]")
    console.print(f"  Tier: {chosen_tier.display_name}")
    console.print(f"    {chosen_tier.capability_note}")
    console.print(f"  GPU: {gpu.vendor.upper() if gpu else 'none'}")
    console.print(f"  PUID/PGID: {final_puid}/{final_pgid}")
    console.print(f"  ComfyUI: {'enabled' if 'comfyui' in enabled_optional else 'disabled'}")
    console.print(f"  InvokeAI: {'enabled' if 'invokeai' in enabled_optional else 'disabled'}")

    compose_exists = (STACK_DIR / "docker-compose.yml").exists()

    confirm_text = (
        "\nThis will overwrite the existing stack/docker-compose.yml. Continue?"
        if compose_exists else
        "\nGenerate the stack with these settings?"
    )

    if not yes and not typer.confirm(confirm_text):
        console.print("Aborted.")
        raise typer.Exit(code=0)

    result = write_stack(config)

    console.print(f"[green]Stack written to {result['compose_path']}[/green]")

    for warning in result["warnings"]:
        console.print(f"[yellow]! {warning}[/yellow]")

    if start is None:
        do_start = False if non_interactive else typer.confirm("Start the stack now?", default=True)
    else:
        do_start = start

    if do_start:

        result = _resolve_port_conflicts(config, result, non_interactive)

        proc = run_docker_command(
            ["docker", "compose", "-f", result["compose_path"], "up", "-d"],
            use_group_workaround=group_just_added
        )

        if proc.returncode == 0:

            console.print("[green]Stack is up.[/green]")

            resolved = resolve_ports(config)
            console.print(f"  Dashboard:    http://localhost:{resolved['dashboard']}")
            console.print(f"  Ollama API:   http://localhost:{resolved['ollama']}")
            console.print(f"  Open WebUI:   http://localhost:{resolved['open-webui']}")

            if "comfyui" in config.enabled_optional:
                console.print(f"  ComfyUI:      http://localhost:{resolved['comfyui']}")

            if "invokeai" in config.enabled_optional:
                console.print(f"  InvokeAI:     http://localhost:{resolved['invokeai']}")

        else:
            console.print("[red]Failed to start the stack - check `docker compose logs`.[/red]")
            raise typer.Exit(code=1)

    else:
        console.print(
            f"Run this when you're ready:\n  docker compose -f {result['compose_path']} up -d"
        )


if __name__ == "__main__":
    app()
