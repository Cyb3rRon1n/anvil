import subprocess

import typer
from rich.console import Console

from installer import __version__
from installer.detect import detect_primary_gpu, detect_system
from installer.generate import (
    STACK_DIR,
    GenerationConfig,
    default_puid_pgid,
    load_previous_state,
    write_stack,
)
from installer.tiers import TIERS, recommend_tier


app = typer.Typer(
    name="anvil",
    help="A GPU-compute creativity forge - inspects your GPU's real VRAM and builds a tailored local AI/creative stack."
)

console = Console()


@app.command()
def version():
    console.print(f"[bold red]Anvil[/bold red] version {__version__}")


def run_docker_command(args: list[str]):
    return subprocess.run(args)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    comfyui: bool | None = typer.Option(
        None, "--comfyui/--no-comfyui",
        help="Include ComfyUI (image generation) - only offered at Heavy tier on NVIDIA GPUs"
    ),
    puid: int | None = typer.Option(None, "--puid"),
    pgid: int | None = typer.Option(None, "--pgid"),
    start: bool | None = typer.Option(None, "--start/--no-start"),
    plain: bool = typer.Option(False, "--plain", help="Use the plain CLI prompts instead of the TUI")
):
    if ctx.invoked_subcommand is not None:
        return

    if not non_interactive and not plain:

        from installer.tui import run_tui

        run_tui()
        return

    run_install(non_interactive, yes, comfyui, puid, pgid, start)


def run_install(
    non_interactive: bool,
    yes: bool,
    comfyui: bool | None,
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

    if not (info.docker_installed and info.docker_running and info.docker_compose_v2):

        console.print(
            "[red]Docker (with Compose v2) needs to already be installed and running - "
            "Anvil doesn't install it for you yet. See https://docs.docker.com/engine/install/[/red]"
        )
        raise typer.Exit(code=1)

    console.print("[green]Docker is ready.[/green]")

    recommendation = recommend_tier(gpu)

    if recommendation.tier is None:

        console.print(f"\n[yellow]{recommendation.explanation}[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]{recommendation.explanation}[/bold]")

    previous = load_previous_state(STACK_DIR)
    default_tier_name = previous["tier"] if previous else recommendation.tier.name

    if non_interactive:
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

        proc = run_docker_command(
            ["docker", "compose", "-f", result["compose_path"], "up", "-d"]
        )

        if proc.returncode == 0:

            console.print("[green]Stack is up.[/green]")
            console.print("  Ollama API:   http://localhost:11434")
            console.print("  Open WebUI:   http://localhost:3000")

            if "comfyui" in config.enabled_optional:
                console.print("  ComfyUI:      http://localhost:8188")

        else:
            console.print("[red]Failed to start the stack - check `docker compose logs`.[/red]")
            raise typer.Exit(code=1)

    else:
        console.print(
            f"Run this when you're ready:\n  docker compose -f {result['compose_path']} up -d"
        )


if __name__ == "__main__":
    app()
