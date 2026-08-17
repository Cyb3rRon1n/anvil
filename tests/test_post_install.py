from unittest.mock import MagicMock, patch

from installer.post_install import verify_stack_running


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
