"""
Operations on an already-running-or-runnable stack - distinct from
preflight.py (is the generated stack ready to start) and
docker_setup.py (is Docker itself ready). Orphaned container cleanup
for the port-conflict remediation flow, and real post-start
verification that the containers docker compose up -d just started
are actually still running.
"""

import json
import shutil
import subprocess
import tarfile
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

from installer.docker_setup import run_docker_command
from installer.generate import STATE_FILENAME


def _parse_compose_ps_json(stdout: str) -> list[dict]:
    """
    docker compose ps --format json's real shape isn't fully pinned
    across Compose versions (some emit a single JSON array, others -
    matching every other docker CLI --format json command - emit one
    object per line/NDJSON); this project has no live Docker in its
    own dev environment to confirm either way, so both are handled
    rather than guessed at from a single assumption.
    """

    stdout = stdout.strip()

    if not stdout:
        return []

    try:
        parsed = json.loads(stdout)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def verify_stack_running(compose_path: str) -> dict:
    """
    Real post-start verification, not just trusting `docker compose up
    -d`'s own exit code - up -d only waits for the initial container
    start, not for the process inside to actually stay up, so a
    container can be reported as started and then immediately
    crash-loop without up -d itself ever reporting a failure. Ported
    from Vulcan's own module of the same name, unchanged - this is
    generic Docker Compose behavior, not project-specific.
    """

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "ps", "--format", "json"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return {
            "all_running": False,
            "error": result.stderr.strip() or "docker compose ps failed",
            "not_running": []
        }

    not_running = [
        {
            "service": container.get("Service", "?"),
            "state": container.get("State", "?"),
            "status": container.get("Status", "")
        }
        for container in _parse_compose_ps_json(result.stdout)
        if container.get("State") != "running"
    ]

    return {"all_running": not not_running, "error": None, "not_running": not_running}


def remove_orphaned_containers(project_name: str) -> dict:
    """
    Narrower than a full uninstall: stops and removes just the
    containers still carrying this project's compose label, by label
    alone (`docker compose -p <project> down`, no -f needed) - and
    never touches stack/ on disk. The port-conflict remediation flow
    calls this for the "your own orphaned containers" case, where
    stack/ is *not* stale - it's the freshly-generated stack the
    current run is actively trying to start, so a full uninstall
    would delete the very compose file this run just wrote.
    """

    down = run_docker_command(["docker", "compose", "-p", project_name, "down"])

    if down.returncode != 0:
        return {"success": False, "error": "Failed to stop orphaned containers - check `docker compose logs`."}

    return {"success": True, "error": None}


def stack_containers_exist(project_name: str) -> bool:
    """
    True if any container (running or stopped) still carries Docker
    Compose's own com.docker.compose.project label for this project -
    ported from Vulcan's post_install.py function of the same name,
    unchanged (generic Docker Compose behavior, not project-specific).
    Used by uninstall_stack() to find containers orphaned by stack/
    being deleted some other way, so a real docker compose down still
    runs even without a compose file on disk to point at.
    """

    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project_name}", "-q"],
            capture_output=True,
            text=True
        )
    except OSError:
        return False

    return result.returncode == 0 and bool(result.stdout.strip())


def uninstall_stack(compose_path: str, stack_dir: Path, purge_data: bool = False) -> dict:
    """
    Stops the running stack and deletes stack/'s config (docker-compose.yml,
    the state file, dashboard/) - but leaves stack/data/ (real downloaded
    models, tens to hundreds of GB) untouched unless purge_data is
    explicitly passed.

    Deliberately NOT a straight port of Vulcan's uninstall_stack(), which
    deletes its whole stack/ tree unconditionally: Vulcan's user data (the
    media library) lives outside stack/ entirely, so that's safe there.
    Anvil's model downloads live inside stack/ (stack/data/<service>) -
    doing the same thing here would silently destroy real,
    expensive-to-redownload weights on every uninstall by default.
    """

    stack_dir = Path(stack_dir)

    if Path(compose_path).exists():

        down = run_docker_command(["docker", "compose", "-f", compose_path, "down"])

        if down.returncode != 0:
            return {"success": False, "error": "Failed to stop the running stack - check `docker compose logs`."}

    elif stack_containers_exist(stack_dir.name):

        down = run_docker_command(["docker", "compose", "-p", stack_dir.name, "down"])

        if down.returncode != 0:
            return {"success": False, "error": "Failed to stop orphaned containers - check `docker compose logs`."}

    if Path(compose_path).exists():
        Path(compose_path).unlink()

    state_path = stack_dir / STATE_FILENAME
    if state_path.exists():
        state_path.unlink()

    dashboard_dir = stack_dir / "dashboard"
    if dashboard_dir.exists():
        shutil.rmtree(dashboard_dir)

    if purge_data:

        data_dir = stack_dir / "data"
        if data_dir.exists():
            shutil.rmtree(data_dir)

    if stack_dir.exists() and not any(stack_dir.iterdir()):
        stack_dir.rmdir()

    return {"success": True, "error": None}


def update_stack(compose_path: str, on_phase=None) -> dict:
    """
    Pull the latest images, then recreate containers - as two distinct
    steps so a pull failure reports distinctly from a recreate failure.
    Ported from Vulcan's update_stack(), simplified: Anvil's compose
    files have no separate --env-file to pass alongside -f.
    """

    if on_phase is not None:
        on_phase("Pull images")

    pull = run_docker_command(["docker", "compose", "-f", compose_path, "pull"])

    if pull.returncode != 0:
        return {"success": False, "error": "Failed to pull images - check `docker compose logs`."}

    if on_phase is not None:
        on_phase("Recreate containers")

    up = run_docker_command(["docker", "compose", "-f", compose_path, "up", "-d"])

    if up.returncode != 0:
        return {"success": False, "error": "Failed to recreate containers - check `docker compose logs`."}

    return {"success": True, "error": None}


def backup_stack(stack_dir: Path, backup_dir: Path = Path("backups")) -> dict:
    """
    Archives docker-compose.yml and the state file only - NOT
    stack/data/. Unlike Vulcan (config/ cleanly separate from the
    external media library), Anvil's stack/data/<service>/ mixes real
    downloaded model weights (tens to hundreds of GB, pointless to
    archive) with per-service settings/workflows in the same
    directories, with no clean, safe boundary between them yet. This
    recovers your tier/service selection without re-running Guided
    Setup; it does not recover Open WebUI chat history, ComfyUI
    workflows, or similar - a real, documented scope limit, not a
    silent gap.
    """

    compose_path = stack_dir / "docker-compose.yml"

    if not compose_path.exists():
        return {"success": False, "error": "No stack found to back up.", "backup_path": None}

    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"anvil-backup-{timestamp}.tar.gz"

    with tarfile.open(backup_path, "w:gz") as tar:

        tar.add(compose_path, arcname="docker-compose.yml")

        state_path = stack_dir / STATE_FILENAME
        if state_path.exists():
            tar.add(state_path, arcname=STATE_FILENAME)

    return {"success": True, "error": None, "backup_path": backup_path}


def restore_stack(backup_path: Path, stack_dir: Path) -> dict:
    """
    Reverses backup_stack(): stops the running stack if any, then
    extracts docker-compose.yml and the state file from the archive
    over stack/. Never touches stack/data/ - not part of what's
    archived, so there's nothing to restore there.
    """

    backup_path = Path(backup_path)

    if not backup_path.exists():
        return {"success": False, "error": f"Backup file not found: {backup_path}"}

    compose_path = stack_dir / "docker-compose.yml"

    if compose_path.exists():

        down = run_docker_command(["docker", "compose", "-f", str(compose_path), "down"])

        if down.returncode != 0:
            return {"success": False, "error": "Failed to stop the running stack - check `docker compose logs`."}

    stack_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(backup_path, "r:gz") as tar:
        tar.extractall(stack_dir, filter="data")

    return {"success": True, "error": None}
