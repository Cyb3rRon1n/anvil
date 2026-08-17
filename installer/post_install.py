"""
Operations on an already-running-or-runnable stack - distinct from
preflight.py (is the generated stack ready to start) and
docker_setup.py (is Docker itself ready). Orphaned container cleanup
for the port-conflict remediation flow, and real post-start
verification that the containers docker compose up -d just started
are actually still running.
"""

import json
import subprocess

from installer.docker_setup import run_docker_command


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
