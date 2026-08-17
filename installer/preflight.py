"""
Checks run once, right before the very first `docker compose up -d`
for a generated stack - distinct from docker_setup.py (is Docker
itself ready) and any post-start operations. check_ports_available()
reads the already-written compose file back and confirms every host
port it publishes is actually free, so a real conflict (something
else already bound to that port) gets reported clearly before
Docker's own opaque failure, not after.
"""

import re
import socket
import subprocess
from pathlib import Path

import yaml


def _port_in_use(port: int) -> bool:

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:

        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            s.bind(("0.0.0.0", port))
            return False
        except OSError:
            return True


def _find_container_on_port(port: int) -> tuple[str, str, str | None] | None:
    """
    The real Docker lookup shared by identify_port_owner() and
    port_owner_is_own_orphan() - one docker ps call, one parse, so the
    two can't ever disagree about what's actually holding a port.

    docker ps's own `--filter publish=<port>` looked like the right
    tool for this but isn't - confirmed for real in Vulcan, not
    assumed: it matched a container on a completely unrelated host port
    during testing, and a container's real container-side port needs
    `expose=` instead. Parsing the real `{{.Ports}}` field directly
    (confirmed against a real bound container) is what's actually
    reliable.
    """

    result = subprocess.run(
        [
            "docker", "ps", "--format",
            '{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Label "com.docker.compose.project"}}'
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return None

    port_pattern = re.compile(rf":{port}->")

    for line in result.stdout.splitlines():

        parts = line.split("\t")

        if len(parts) != 4:
            continue

        name, image, ports_field, compose_project = parts

        if not port_pattern.search(ports_field):
            continue

        return name, image, (compose_project or None)

    return None


def identify_port_owner(port: int, own_project_name: str | None = None) -> str | None:
    """
    Best-effort diagnosis of what's actually holding a conflicting
    port, so a refusal names a real cause instead of just a number -
    the exact gap that turned the original cAdvisor-vs-qBittorrent
    incident in Vulcan into a confusing debugging session instead of an
    obvious one. Docker-only: this project's one hard dependency is
    already Docker itself, so this needs no new tool (no lsof/ss
    requirement) - if the port isn't held by a Docker container, this
    honestly returns None rather than guessing further.
    """

    found = _find_container_on_port(port)

    if found is None:
        return None

    name, image, compose_project = found

    if own_project_name and compose_project == own_project_name:
        return (
            f"your own orphaned containers from a previous stack (project "
            f"\"{compose_project}\") - stop them with: "
            f"docker compose -p {compose_project} down"
        )

    return f"container \"{name}\" (image {image})"


def port_owner_is_own_orphan(port: int, own_project_name: str | None) -> bool:
    """
    Structured counterpart to identify_port_owner()'s human-readable
    string - lets a caller branch on "is this the safe, automatable
    case" without parsing prose. Reuses the exact same lookup, so the
    two functions can never disagree about a given port.
    """

    if not own_project_name:
        return False

    found = _find_container_on_port(port)

    return found is not None and found[2] == own_project_name


def check_ports_available(compose_path: str) -> dict:

    compose_path = Path(compose_path)
    parsed = yaml.safe_load(compose_path.read_text()) or {}
    port_services: dict[int, str] = {}

    for service_name, service in parsed.get("services", {}).items():

        for entry in service.get("ports", []):

            host_port = int(str(entry).split(":")[-2])
            port_services[host_port] = service_name

    conflicts = sorted(port for port in port_services if _port_in_use(port))
    own_project_name = compose_path.parent.name

    owners = {
        port: identify_port_owner(port, own_project_name=own_project_name)
        for port in conflicts
    }
    own_orphan = {
        port: port_owner_is_own_orphan(port, own_project_name)
        for port in conflicts
    }

    return {
        "available": not conflicts,
        "conflicts": conflicts,
        "owners": owners,
        "port_services": {port: port_services[port] for port in conflicts},
        "own_orphan": own_orphan,
    }


def format_port_conflicts(port_check: dict) -> str:
    """
    Single source of truth for the conflict message text, shared by
    both the CLI and the whiptail menu rather than each building its own -
    keeps the two genuinely identical instead of drifting apart.
    """

    lines = []

    for port in port_check["conflicts"]:

        owner = port_check["owners"].get(port)

        if owner:
            lines.append(f"  {port}: {owner}")
        else:
            lines.append(f"  {port}: not identified as a Docker container - check for a native service")

    return "\n".join(lines)
