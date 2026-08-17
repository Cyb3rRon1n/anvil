"""
Operations on an already-running-or-runnable stack - distinct from
preflight.py (is the generated stack ready to start) and
docker_setup.py (is Docker itself ready). Currently just orphaned
container cleanup for the port-conflict remediation flow.
"""

from installer.docker_setup import run_docker_command


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
