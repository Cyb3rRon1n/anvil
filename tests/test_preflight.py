import socket
from unittest.mock import patch

import pytest

from installer.preflight import (
    _find_container_on_port,
    _port_in_use,
    check_ports_available,
    format_port_conflicts,
    identify_port_owner,
    port_owner_is_own_orphan,
)


def test_port_in_use_returns_true_when_port_is_bound():

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)

        assert _port_in_use(port) is True


def test_port_in_use_returns_false_when_port_is_free():

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    s.close()
    assert _port_in_use(port) is False


def test_check_ports_available_returns_available_when_no_conflicts(tmp_path):

    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  ollama:\n"
        "    ports:\n"
        "      - \"11434:11434\"\n"
    )

    with patch("installer.preflight._port_in_use", return_value=False):
        result = check_ports_available(str(compose))

    assert result["available"] is True
    assert result["conflicts"] == []


def test_check_ports_available_detects_conflicting_port(tmp_path):

    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  ollama:\n"
        "    ports:\n"
        "      - \"11434:11434\"\n"
    )

    with (
        patch("installer.preflight._port_in_use", side_effect=lambda port: port == 11434),
        patch("installer.preflight._find_container_on_port", return_value=None),
    ):
        result = check_ports_available(str(compose))

    assert result["available"] is False
    assert 11434 in result["conflicts"]
    assert result["port_services"][11434] == "ollama"


def test_check_ports_available_maps_multiple_services_to_ports(tmp_path):

    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  ollama:\n"
        "    ports:\n"
        "      - \"11434:11434\"\n"
        "  open-webui:\n"
        "    ports:\n"
        "      - \"3000:8080\"\n"
    )

    with (
        patch("installer.preflight._port_in_use", side_effect=lambda port: port == 3000),
        patch("installer.preflight._find_container_on_port", return_value=None),
    ):
        result = check_ports_available(str(compose))

    assert result["available"] is False
    assert result["conflicts"] == [3000]
    assert result["port_services"][3000] == "open-webui"


def test_identify_port_owner_returns_none_when_not_docker():

    with patch("installer.preflight._find_container_on_port", return_value=None):
        result = identify_port_owner(11434)

    assert result is None


def test_identify_port_owner_returns_container_info():

    with patch("installer.preflight._find_container_on_port", return_value=("my-ollama", "ollama/ollama:latest", "some-other-project")):
        result = identify_port_owner(11434)

    assert "my-ollama" in result
    assert "ollama/ollama:latest" in result


def test_identify_port_owner_identifies_own_orphan():

    with patch("installer.preflight._find_container_on_port", return_value=("my-ollama", "ollama/ollama:latest", "anvil")):
        result = identify_port_owner(11434, own_project_name="anvil")

    assert "orphaned containers" in result
    assert "anvil" in result


def test_port_owner_is_own_orphan_true_when_project_matches():

    with patch("installer.preflight._find_container_on_port", return_value=("c1", "img", "anvil")):
        assert port_owner_is_own_orphan(11434, "anvil") is True


def test_port_owner_is_own_orphan_false_when_project_differs():

    with patch("installer.preflight._find_container_on_port", return_value=("c1", "img", "other-project")):
        assert port_owner_is_own_orphan(11434, "anvil") is False


def test_port_owner_is_own_orphan_false_when_no_project_name():

    with patch("installer.preflight._find_container_on_port", return_value=("c1", "img", "anvil")):
        assert port_owner_is_own_orphan(11434, None) is False


def test_format_port_conflicts_with_owner():

    port_check = {
        "conflicts": [11434],
        "owners": {11434: "container \"my-ollama\" (image ollama/ollama:latest)"},
        "port_services": {11434: "ollama"},
        "own_orphan": {11434: False},
    }

    result = format_port_conflicts(port_check)

    assert "11434" in result
    assert "my-ollama" in result


def test_format_port_conflicts_without_owner():

    port_check = {
        "conflicts": [11434],
        "owners": {11434: None},
        "port_services": {11434: "ollama"},
        "own_orphan": {11434: False},
    }

    result = format_port_conflicts(port_check)

    assert "11434" in result
    assert "not identified as a Docker container" in result


def test_format_port_conflicts_multiple_ports():

    port_check = {
        "conflicts": [11434, 3000],
        "owners": {11434: "container \"c1\" (image img1)", 3000: None},
        "port_services": {11434: "ollama", 3000: "open-webui"},
        "own_orphan": {11434: False, 3000: False},
    }

    result = format_port_conflicts(port_check)

    assert "11434" in result
    assert "3000" in result
