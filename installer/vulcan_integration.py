"""
Optional integration with a co-located Vulcan install
(github.com/Cyb3rRon1n/vulcan) - a genuinely novel capability neither
Anvil nor Osmantic/ODS has on its own. ODS is a fully self-contained
install (its own reverse proxy, its own mDNS hostnames, its own
dashboard) with no notion of merging into an existing homelab at all.
When a real Vulcan stack is found alongside Anvil's own, this
cross-checks Vulcan's real *configured* ports (catching a conflict even
when Vulcan isn't currently running - detect.py's port_in_use() alone
only ever sees what's live right now) and can add a section to
Vulcan's already-generated Homepage dashboard. Detection-and-confirm is
a CLI/menu-layer concern - every function here is a pure, non-prompting
engine function, same split as every other module in this project.

Falls back to Anvil's own standalone dashboard, completely unchanged,
whenever no Vulcan stack is found nearby - this integration is purely
additive, never a replacement for anything Anvil already does.
"""

from pathlib import Path

import yaml


VULCAN_STATE_FILENAME = ".vulcan-state.json"
VULCAN_HOMEPAGE_GROUP = "Creative Suite (Anvil)"


def find_vulcan_stack(search_paths: list[Path] | None = None) -> Path | None:
    """
    Real positive identification, not a name/file-shape guess: only a
    directory holding Vulcan's own state file (.vulcan-state.json,
    written by its own generate.py:save_state()) counts as a real
    Vulcan stack - any other docker-compose.yml lying around is just
    some other project's, not Vulcan's.

    Default search path matches this project's own real, current
    workspace layout (anvil/ and vulcan/ as sibling directories under
    one multi-repo root, confirmed via my-repos/AGENTS.md) - a sibling
    "vulcan" directory relative to the current working directory,
    which is where `anvil` is actually run from in practice (a repo
    checkout, not an arbitrary path). Override with search_paths for
    any other layout.
    """

    if search_paths is None:

        cwd = Path.cwd().resolve()
        search_paths = [cwd.parent / "vulcan" / "stack", cwd / "vulcan" / "stack"]

    for path in search_paths:

        if (path / VULCAN_STATE_FILENAME).exists():
            return path

    return None


def parse_compose_ports(compose_path: Path) -> dict[int, str]:
    """
    Real published host ports straight from a rendered compose file -
    the one honest source. A static per-project port table (like this
    project's own SERVICE_PORTS) can drift from real port_overrides
    already applied - Vulcan's own port-conflict remediation already
    remaps services like this on a real host (confirmed while testing
    this module: a real Vulcan stack generated for this verification
    had metube pre-remapped to 8082 by Vulcan's own conflict handling).
    """

    parsed = yaml.safe_load(compose_path.read_text()) or {}
    ports: dict[int, str] = {}

    for service_name, service in parsed.get("services", {}).items():

        for entry in service.get("ports", []) or []:

            host_port = int(str(entry).split(":")[-2])
            ports[host_port] = service_name

    return ports


def check_vulcan_port_conflicts(anvil_ports: dict[str, int], vulcan_stack_dir: Path) -> list[str]:
    """
    Static cross-reference, not a live probe - detect.py's own
    port_in_use() (used elsewhere in this project) already catches a
    conflict against anything actually running right now, Vulcan
    included. What that alone can't catch: Vulcan stopped, Anvil
    generates first, both configured for the same port - free right
    now, guaranteed to collide the moment both stacks are ever started
    together. Reading Vulcan's real rendered compose file closes that
    gap.
    """

    compose_path = vulcan_stack_dir / "docker-compose.yml"

    if not compose_path.exists():
        return []

    vulcan_ports = parse_compose_ports(compose_path)
    warnings = []

    for anvil_key, anvil_port in anvil_ports.items():

        vulcan_service = vulcan_ports.get(anvil_port)

        if vulcan_service is not None:

            warnings.append(
                f"Port {anvil_port} ({anvil_key}) is already configured for Vulcan's "
                f"{vulcan_service} service ({compose_path}) - even if Vulcan isn't "
                "running right now, both stacks can't bind this port at the same time."
            )

    return warnings


def build_homepage_tiles(enabled: set[str], ports: dict[str, int], host: str) -> list[dict]:
    """
    Mirrors Vulcan's own render_homepage_services() tile shape exactly
    ({display_name: {href, icon, description}}) so a merged group
    renders identically to Vulcan's native ones. Same restrained
    tile selection as Anvil's own dashboard.html.j2 - real destinations
    a user would actually click into, not every enabled container
    (embeddings/qdrant's storage backend has no useful UI of its own).

    Takes enabled/ports as plain data rather than a GenerationConfig so
    this module never has to import generate.py/tiers.py - Anvil's own
    engine modules stay a one-way dependency graph, this is a leaf.
    """

    candidates = [
        ("open-webui", "Open WebUI", "Chat with your local models"),
        ("comfyui", "ComfyUI", "Image generation"),
        ("invokeai", "InvokeAI", "Turnkey image generation"),
        ("n8n", "n8n", "Workflow automation"),
        ("qdrant", "Qdrant", "Vector database console (RAG)"),
    ]

    tiles = []

    for key, display_name, description in candidates:

        if key not in enabled:
            continue

        href = f"http://{host}:{ports[key]}"

        if key == "qdrant":
            href += "/dashboard"

        tiles.append({display_name: {"href": href, "icon": f"{key}.png", "description": description}})

    return tiles


def merge_into_vulcan_homepage(vulcan_stack_dir: Path, tiles: list[dict]) -> bool:
    """
    Vulcan's own services.yaml is write-once from Vulcan's side
    (generate.py never overwrites it once it exists) specifically so a
    user's own edits stay safe - this module respects that by owning
    exactly one named group (VULCAN_HOMEPAGE_GROUP) and never touching
    any other group in the file. Unlike Vulcan's own write-once rule,
    this group IS replaced on every call - nothing in it is
    user-hand-edited (only Anvil's own tiles ever live here), so a
    rerun with a different enabled-service set should update the tile
    list, not go stale.

    Returns False (no merge happened) when Vulcan has no Homepage
    enabled - the file to merge into doesn't exist yet, and this
    module never creates one, since that's Vulcan's own installer's
    call to make, not Anvil's.
    """

    services_yaml_path = vulcan_stack_dir / "config" / "homepage" / "services.yaml"

    if not services_yaml_path.exists():
        return False

    groups = yaml.safe_load(services_yaml_path.read_text()) or []
    groups = [g for g in groups if VULCAN_HOMEPAGE_GROUP not in g]

    if not tiles:
        # Nothing of ours to show - write back with our group removed
        # (e.g. a prior run's tiles) but otherwise untouched.
        services_yaml_path.write_text(yaml.safe_dump(groups, sort_keys=False))
        return True

    # Vulcan's own render_homepage_services() always appends a
    # "Guides" group last - insert ahead of it so Anvil's section
    # doesn't visually trail the walkthrough link, purely cosmetic but
    # matches how a human editing the file by hand would place it.
    insert_at = next((i for i, g in enumerate(groups) if "Guides" in g), len(groups))
    groups.insert(insert_at, {VULCAN_HOMEPAGE_GROUP: tiles})

    services_yaml_path.write_text(yaml.safe_dump(groups, sort_keys=False))
    return True
