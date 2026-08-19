import yaml

from installer.vulcan_integration import (
    VULCAN_HOMEPAGE_GROUP,
    build_homepage_tiles,
    check_vulcan_port_conflicts,
    find_vulcan_stack,
    merge_into_vulcan_homepage,
    parse_compose_ports,
)


def make_vulcan_stack(tmp_path, ports=None, with_homepage=True):
    """
    A real-shaped (not just any docker-compose.yml) Vulcan stack dir -
    the state file is the real positive-identification signal
    find_vulcan_stack() looks for.
    """

    stack_dir = tmp_path / "vulcan" / "stack"
    stack_dir.mkdir(parents=True)
    (stack_dir / ".vulcan-state.json").write_text("{}")

    ports = ports or {"jellyfin": 8096, "homepage": 3000}
    services = {
        name: {"ports": [f"{port}:{port}"]}
        for name, port in ports.items()
    }
    (stack_dir / "docker-compose.yml").write_text(
        yaml.safe_dump({"services": services})
    )

    if with_homepage:

        homepage_dir = stack_dir / "config" / "homepage"
        homepage_dir.mkdir(parents=True)
        (homepage_dir / "services.yaml").write_text(
            yaml.safe_dump([
                {"Media": [{"Jellyfin": {"href": "http://x:8096", "icon": "jellyfin.png", "description": "d"}}]},
                {"Guides": [{"Setup Walkthrough": {"href": "http://x", "icon": "github.png", "description": "d"}}]},
            ], sort_keys=False)
        )

    return stack_dir


def test_find_vulcan_stack_default_search_uses_sibling_directory(tmp_path, monkeypatch):
    """
    Default search path (no explicit search_paths) matches this
    project's own real workspace layout: anvil/ and vulcan/ as sibling
    repos, so a sibling "vulcan" dir relative to cwd is checked first.
    """

    workspace = tmp_path / "workspace"
    anvil_dir = workspace / "anvil"
    anvil_dir.mkdir(parents=True)
    make_vulcan_stack(workspace, with_homepage=False)

    monkeypatch.chdir(anvil_dir)

    found = find_vulcan_stack()
    assert found == workspace / "vulcan" / "stack"


def test_find_vulcan_stack_finds_real_state_file(tmp_path):

    stack_dir = make_vulcan_stack(tmp_path)

    found = find_vulcan_stack(search_paths=[stack_dir])
    assert found == stack_dir


def test_find_vulcan_stack_returns_none_when_no_state_file(tmp_path):

    fake_dir = tmp_path / "not-vulcan" / "stack"
    fake_dir.mkdir(parents=True)
    (fake_dir / "docker-compose.yml").write_text("services: {}")

    assert find_vulcan_stack(search_paths=[fake_dir]) is None


def test_find_vulcan_stack_ignores_any_docker_compose_without_state_file(tmp_path):
    """
    A real positive ID, not a name/shape guess - some other project's
    docker-compose.yml must never be mistaken for Vulcan's.
    """

    other_dir = tmp_path / "some-other-project" / "stack"
    other_dir.mkdir(parents=True)
    (other_dir / "docker-compose.yml").write_text(
        yaml.safe_dump({"services": {"jellyfin": {"ports": ["8096:8096"]}}})
    )

    assert find_vulcan_stack(search_paths=[other_dir]) is None


def test_parse_compose_ports_reads_real_published_ports(tmp_path):

    stack_dir = make_vulcan_stack(tmp_path, ports={"jellyfin": 8096, "radarr": 7878})
    ports = parse_compose_ports(stack_dir / "docker-compose.yml")

    assert ports == {8096: "jellyfin", 7878: "radarr"}


def test_check_vulcan_port_conflicts_finds_real_overlap(tmp_path):

    stack_dir = make_vulcan_stack(tmp_path, ports={"homepage": 3000})

    warnings = check_vulcan_port_conflicts({"open-webui": 3000}, stack_dir)

    assert len(warnings) == 1
    assert "3000" in warnings[0]
    assert "homepage" in warnings[0]


def test_check_vulcan_port_conflicts_no_overlap_produces_no_warning(tmp_path):

    stack_dir = make_vulcan_stack(tmp_path, ports={"jellyfin": 8096})

    warnings = check_vulcan_port_conflicts({"open-webui": 3000, "ollama": 11434}, stack_dir)

    assert warnings == []


def test_check_vulcan_port_conflicts_missing_compose_returns_empty(tmp_path):

    stack_dir = tmp_path / "vulcan" / "stack"
    stack_dir.mkdir(parents=True)

    assert check_vulcan_port_conflicts({"open-webui": 3000}, stack_dir) == []


def test_build_homepage_tiles_only_includes_enabled_and_user_facing_services():

    tiles = build_homepage_tiles(
        enabled={"ollama", "open-webui", "qdrant", "embeddings"},
        ports={"open-webui": 3000, "qdrant": 6333, "embeddings": 8090},
        host="192.168.1.50"
    )

    names = [list(t.keys())[0] for t in tiles]

    # ollama has no useful web UI (matches dashboard.html.j2's own
    # omission); embeddings is a backend service with no UI at all.
    assert "Ollama" not in names
    assert "Embeddings" not in names
    assert names == ["Open WebUI", "Qdrant"]


def test_build_homepage_tiles_qdrant_links_to_its_dashboard_path():

    tiles = build_homepage_tiles(enabled={"qdrant"}, ports={"qdrant": 6333}, host="192.168.1.50")

    assert tiles[0]["Qdrant"]["href"] == "http://192.168.1.50:6333/dashboard"


def test_merge_into_vulcan_homepage_adds_group_before_guides(tmp_path):

    stack_dir = make_vulcan_stack(tmp_path)
    tiles = [{"Open WebUI": {"href": "http://x:3000", "icon": "open-webui.png", "description": "d"}}]

    merged = merge_into_vulcan_homepage(stack_dir, tiles)

    assert merged is True

    groups = yaml.safe_load((stack_dir / "config" / "homepage" / "services.yaml").read_text())
    group_names = [list(g.keys())[0] for g in groups]

    assert group_names == ["Media", VULCAN_HOMEPAGE_GROUP, "Guides"]
    assert groups[1][VULCAN_HOMEPAGE_GROUP] == tiles


def test_merge_into_vulcan_homepage_never_touches_other_groups(tmp_path):

    stack_dir = make_vulcan_stack(tmp_path)
    original_media_group = yaml.safe_load(
        (stack_dir / "config" / "homepage" / "services.yaml").read_text()
    )[0]

    merge_into_vulcan_homepage(stack_dir, [{"n8n": {"href": "http://x", "icon": "n8n.png", "description": "d"}}])

    groups = yaml.safe_load((stack_dir / "config" / "homepage" / "services.yaml").read_text())
    assert groups[0] == original_media_group


def test_merge_into_vulcan_homepage_replaces_not_duplicates_on_rerun(tmp_path):

    stack_dir = make_vulcan_stack(tmp_path)

    merge_into_vulcan_homepage(
        stack_dir, [{"Open WebUI": {"href": "http://x:3000", "icon": "open-webui.png", "description": "d"}}]
    )
    merge_into_vulcan_homepage(
        stack_dir, [{"n8n": {"href": "http://x:5678", "icon": "n8n.png", "description": "d"}}]
    )

    groups = yaml.safe_load((stack_dir / "config" / "homepage" / "services.yaml").read_text())
    matching = [g for g in groups if VULCAN_HOMEPAGE_GROUP in g]

    assert len(matching) == 1
    assert matching[0][VULCAN_HOMEPAGE_GROUP] == [
        {"n8n": {"href": "http://x:5678", "icon": "n8n.png", "description": "d"}}
    ]


def test_merge_into_vulcan_homepage_empty_tiles_removes_the_group(tmp_path):
    """
    A rerun with everything disabled shouldn't leave a stale, empty
    Creative Suite group behind.
    """

    stack_dir = make_vulcan_stack(tmp_path)

    merge_into_vulcan_homepage(
        stack_dir, [{"n8n": {"href": "http://x", "icon": "n8n.png", "description": "d"}}]
    )
    merged = merge_into_vulcan_homepage(stack_dir, [])

    assert merged is True

    groups = yaml.safe_load((stack_dir / "config" / "homepage" / "services.yaml").read_text())
    assert not any(VULCAN_HOMEPAGE_GROUP in g for g in groups)


def test_merge_into_vulcan_homepage_returns_false_when_homepage_not_enabled(tmp_path):

    stack_dir = make_vulcan_stack(tmp_path, with_homepage=False)

    merged = merge_into_vulcan_homepage(stack_dir, [{"n8n": {"href": "http://x", "icon": "n8n.png", "description": "d"}}])

    assert merged is False
