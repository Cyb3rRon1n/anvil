from pathlib import Path
from unittest.mock import MagicMock, patch

from installer.generate import STATE_FILENAME
from installer.post_install import (
    backup_stack,
    restore_stack,
    stack_containers_exist,
    uninstall_stack,
    update_stack,
    verify_stack_running,
)


def test_verify_stack_running_all_healthy_ndjson():

    ndjson = (
        '{"Name":"ollama","Service":"ollama","State":"running","Status":"Up 2 minutes"}\n'
        '{"Name":"open-webui","Service":"open-webui","State":"running","Status":"Up 2 minutes (healthy)"}\n'
    )
    proc = MagicMock(returncode=0, stdout=ndjson, stderr="")

    with patch("installer.post_install.subprocess.run", return_value=proc):

        result = verify_stack_running("stack/docker-compose.yml")

    assert result == {"all_running": True, "error": None, "not_running": []}


def test_verify_stack_running_detects_crashed_container_json_array():

    array = (
        '[{"Name":"ollama","Service":"ollama","State":"running","Status":"Up 2 minutes"},'
        '{"Name":"open-webui","Service":"open-webui","State":"exited","Status":"Exited (1) 5 seconds ago"}]'
    )
    proc = MagicMock(returncode=0, stdout=array, stderr="")

    with patch("installer.post_install.subprocess.run", return_value=proc):

        result = verify_stack_running("stack/docker-compose.yml")

    assert result == {
        "all_running": False,
        "error": None,
        "not_running": [
            {"service": "open-webui", "state": "exited", "status": "Exited (1) 5 seconds ago"}
        ]
    }


def test_verify_stack_running_ps_command_failure():

    proc = MagicMock(returncode=1, stdout="", stderr="no such project")

    with patch("installer.post_install.subprocess.run", return_value=proc):

        result = verify_stack_running("stack/docker-compose.yml")

    assert result == {"all_running": False, "error": "no such project", "not_running": []}


def test_stack_containers_exist_true_when_labeled_containers_found():

    proc = MagicMock(returncode=0, stdout="abc123\n")

    with patch("installer.post_install.subprocess.run", return_value=proc):

        assert stack_containers_exist("stack") is True


def test_stack_containers_exist_false_when_none_found():

    proc = MagicMock(returncode=0, stdout="")

    with patch("installer.post_install.subprocess.run", return_value=proc):

        assert stack_containers_exist("stack") is False


def test_stack_containers_exist_false_on_docker_missing():

    with patch("installer.post_install.subprocess.run", side_effect=OSError):

        assert stack_containers_exist("stack") is False


def _make_stack(tmp_path, with_data=True):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}")
    (stack_dir / STATE_FILENAME).write_text("{}")
    (stack_dir / "dashboard").mkdir()
    (stack_dir / "dashboard" / "index.html").write_text("<html></html>")

    if with_data:
        (stack_dir / "data" / "ollama").mkdir(parents=True)
        (stack_dir / "data" / "ollama" / "model.bin").write_text("not a real model")

    return stack_dir


def test_uninstall_stack_removes_config_but_keeps_data_by_default(tmp_path):

    stack_dir = _make_stack(tmp_path)
    down = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=down):

        result = uninstall_stack(str(stack_dir / "docker-compose.yml"), stack_dir)

    assert result == {"success": True, "error": None}
    assert not (stack_dir / "docker-compose.yml").exists()
    assert not (stack_dir / STATE_FILENAME).exists()
    assert not (stack_dir / "dashboard").exists()
    assert (stack_dir / "data" / "ollama" / "model.bin").exists()


def test_uninstall_stack_purge_data_removes_downloaded_models(tmp_path):

    stack_dir = _make_stack(tmp_path)
    down = MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", return_value=down):

        result = uninstall_stack(str(stack_dir / "docker-compose.yml"), stack_dir, purge_data=True)

    assert result == {"success": True, "error": None}
    assert not (stack_dir / "data").exists()
    assert not stack_dir.exists()


def test_uninstall_stack_compose_down_failure(tmp_path):

    stack_dir = _make_stack(tmp_path)
    down = MagicMock(returncode=1)

    with patch("installer.post_install.run_docker_command", return_value=down):

        result = uninstall_stack(str(stack_dir / "docker-compose.yml"), stack_dir)

    assert result["success"] is False
    assert "Failed to stop the running stack" in result["error"]
    assert (stack_dir / "docker-compose.yml").exists()


def test_uninstall_stack_uses_orphan_cleanup_when_no_compose_file(tmp_path):

    stack_dir = tmp_path / "stack"

    with patch("installer.post_install.stack_containers_exist", return_value=True), patch(
        "installer.post_install.run_docker_command", return_value=MagicMock(returncode=0)
    ) as mock_run:

        result = uninstall_stack(str(stack_dir / "docker-compose.yml"), stack_dir)

    assert result == {"success": True, "error": None}
    mock_run.assert_called_once_with(["docker", "compose", "-p", "stack", "down"])


def test_update_stack_success_calls_pull_then_up():

    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("installer.post_install.run_docker_command", side_effect=fake_run):

        result = update_stack("stack/docker-compose.yml")

    assert result == {"success": True, "error": None}
    assert calls[0] == ["docker", "compose", "-f", "stack/docker-compose.yml", "pull"]
    assert calls[1] == ["docker", "compose", "-f", "stack/docker-compose.yml", "up", "-d"]


def test_update_stack_pull_failure_skips_recreate():

    with patch(
        "installer.post_install.run_docker_command", return_value=MagicMock(returncode=1)
    ) as mock_run:

        result = update_stack("stack/docker-compose.yml")

    assert result["success"] is False
    assert "pull images" in result["error"]
    mock_run.assert_called_once()


def test_backup_stack_no_stack_found():

    result = backup_stack(Path("/nonexistent/stack"))

    assert result["success"] is False
    assert result["backup_path"] is None


def test_backup_and_restore_stack_round_trip(tmp_path):

    stack_dir = _make_stack(tmp_path)
    backup_dir = tmp_path / "backups"

    with patch("installer.post_install.run_docker_command", return_value=MagicMock(returncode=0)):

        backup_result = backup_stack(stack_dir, backup_dir=backup_dir)
        assert backup_result["success"] is True
        assert backup_result["backup_path"].exists()

        (stack_dir / "docker-compose.yml").unlink()
        (stack_dir / STATE_FILENAME).unlink()

        restore_result = restore_stack(backup_result["backup_path"], stack_dir)

    assert restore_result == {"success": True, "error": None}
    assert (stack_dir / "docker-compose.yml").read_text() == "services: {}"
    assert (stack_dir / STATE_FILENAME).exists()
    assert (stack_dir / "data" / "ollama" / "model.bin").exists()


def test_restore_stack_missing_backup_file(tmp_path):

    result = restore_stack(tmp_path / "does-not-exist.tar.gz", tmp_path / "stack")

    assert result["success"] is False
    assert "not found" in result["error"]
