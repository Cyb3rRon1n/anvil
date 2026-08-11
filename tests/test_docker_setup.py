from unittest.mock import MagicMock, patch

from installer.docker_setup import (
    _docker_group_gid,
    _user_in_docker_group,
    add_user_to_docker_group,
    ensure_compose_v2,
    install_docker,
    install_plan_for,
    run_docker_command,
    start_docker_service,
)


def test_install_plan_for_docker_script_distros():

    for os_id in ("ubuntu", "debian", "raspbian", "fedora"):

        plan = install_plan_for(os_id)

        assert plan["method"] == "get.docker.com"
        assert plan["needs_reboot"] is False


def test_install_plan_for_arch():

    plan = install_plan_for("arch")

    assert plan["method"] == "pacman"
    assert plan["needs_reboot"] is False


def test_install_plan_for_unsupported_distro():

    assert install_plan_for("gentoo") is None
    assert install_plan_for(None) is None


def test_install_plan_for_atomic_host_overrides_os_id():
    """
    A real, load-bearing case: a Bazzite/Kinoite host reports
    os_id="fedora" (ID_LIKE=fedora), which would otherwise route
    through the plain get.docker.com script - wrong, since the base
    image is read-only. os_is_atomic must win regardless of os_id.
    """

    plan = install_plan_for("fedora", os_is_atomic=True)

    assert plan["method"] == "rpm-ostree"
    assert plan["needs_reboot"] is True
    assert "rpm-ostree install" in plan["description"]


def test_install_docker_runs_get_docker_script_for_ubuntu():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run:

        result = install_docker("ubuntu")

    assert result == {
        "success": True,
        "error": None,
        "method": "get.docker.com",
        "needs_reboot": False
    }
    mock_run.assert_called_once_with(
        ["sh", "-c", "curl -fsSL https://get.docker.com | sh"]
    )


def test_install_docker_runs_pacman_for_arch():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run:

        result = install_docker("arch")

    assert result == {
        "success": True,
        "error": None,
        "method": "pacman",
        "needs_reboot": False
    }
    mock_run.assert_called_once_with(
        ["pacman", "-Sy", "--noconfirm", "docker"]
    )


def test_install_docker_returns_clean_failure_for_unsupported_distro():

    result = install_docker("gentoo")

    assert result == {
        "success": False,
        "error": "No known install method for 'gentoo'",
        "method": None,
        "needs_reboot": False
    }


def test_install_docker_atomic_adds_repo_then_layers_packages():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run:

        result = install_docker("fedora", os_is_atomic=True)

    assert result["success"] is True
    assert result["method"] == "rpm-ostree"
    assert result["needs_reboot"] is True

    assert mock_run.call_count == 2

    repo_call, layer_call = mock_run.call_args_list

    assert repo_call.args[0][:2] == ["sh", "-c"]
    assert "docker-ce.repo" in repo_call.args[0][2]

    assert layer_call.args[0][:2] == ["rpm-ostree", "install"]
    assert "docker-ce" in layer_call.args[0]
    assert "docker-compose-plugin" in layer_call.args[0]


def test_install_docker_atomic_stops_if_repo_add_fails():
    """
    A real failure at the repo-add step must not go on to attempt
    rpm-ostree install anyway - and must not claim needs_reboot, since
    nothing was actually layered.
    """

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": False, "error": "network unreachable"}
    ) as mock_run:

        result = install_docker("fedora", os_is_atomic=True)

    assert result["success"] is False
    assert "failed to add Docker's repo" in result["error"]
    assert result["needs_reboot"] is False
    mock_run.assert_called_once()


def test_install_docker_atomic_layer_failure_reports_no_reboot_needed():
    """
    Repo add succeeds but the actual rpm-ostree install fails (e.g. a
    conflicting layered package) - needs_reboot must be False, there's
    nothing pending a reboot would pick up.
    """

    with patch(
        "installer.docker_setup.run_privileged",
        side_effect=[
            {"success": True, "error": None},
            {"success": False, "error": "exit code 1"}
        ]
    ):

        result = install_docker("fedora", os_is_atomic=True)

    assert result["success"] is False
    assert result["needs_reboot"] is False


def test_ensure_compose_v2_short_circuits_when_already_working():

    with patch("installer.docker_setup.run_ok", return_value=True), patch(
        "installer.docker_setup.run_privileged"
    ) as mock_run_privileged:

        result = ensure_compose_v2("fedora")

    assert result == {"success": True, "error": None}
    mock_run_privileged.assert_not_called()


def test_ensure_compose_v2_arch_fallback_succeeds():

    with patch(
        "installer.docker_setup.run_ok", side_effect=[False, True]
    ), patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run_privileged:

        result = ensure_compose_v2("arch")

    assert result == {"success": True, "error": None}
    mock_run_privileged.assert_called_once_with(
        ["pacman", "-S", "--noconfirm", "docker-compose"]
    )


def test_ensure_compose_v2_still_fails_after_arch_fallback():

    with patch(
        "installer.docker_setup.run_ok", side_effect=[False, False]
    ), patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ):

        result = ensure_compose_v2("arch")

    assert result == {
        "success": False,
        "error": "docker compose v2 not available after install"
    }


def test_ensure_compose_v2_non_arch_fails_without_fallback_attempt():

    with patch("installer.docker_setup.run_ok", return_value=False), patch(
        "installer.docker_setup.run_privileged"
    ) as mock_run_privileged:

        result = ensure_compose_v2("fedora")

    assert result == {
        "success": False,
        "error": "docker compose v2 not available after install"
    }
    mock_run_privileged.assert_not_called()


def test_add_user_to_docker_group_calls_usermod_and_returns_early_when_it_really_worked():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run, patch(
        "installer.docker_setup._user_in_docker_group", return_value=True
    ):

        result = add_user_to_docker_group("sentinel")

    assert result == {"success": True, "error": None}
    mock_run.assert_called_once_with(["usermod", "-aG", "docker", "sentinel"])


def test_add_user_to_docker_group_falls_back_when_usermod_silently_no_ops():
    """
    The exact bug found live against msi-laptop (Bazzite): usermod
    reports success but writes nothing when the docker group's
    canonical record lives only in /usr/lib/group (systemd-sysusers,
    not present in /etc/group at all). A real functional check
    (_user_in_docker_group) catches usermod's false claim of success,
    and the fallback creates a local merge-friendly /etc/group entry
    before using gpasswd to manage membership on it - verified this
    exact sequence live end to end against the real host.
    """

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run, patch(
        "installer.docker_setup._user_in_docker_group", side_effect=[False, True]
    ), patch(
        "installer.docker_setup._docker_group_gid", return_value="958"
    ):

        result = add_user_to_docker_group("sentinel")

    assert result == {"success": True, "error": None}
    assert mock_run.call_count == 3

    usermod_call, ensure_entry_call, gpasswd_call = mock_run.call_args_list

    assert usermod_call.args[0] == ["usermod", "-aG", "docker", "sentinel"]
    assert ensure_entry_call.args[0][:2] == ["sh", "-c"]
    assert "docker:x:958:" in ensure_entry_call.args[0][2]
    assert gpasswd_call.args[0] == ["gpasswd", "-a", "sentinel", "docker"]


def test_add_user_to_docker_group_fallback_fails_cleanly_when_group_truly_missing():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ), patch(
        "installer.docker_setup._user_in_docker_group", return_value=False
    ), patch(
        "installer.docker_setup._docker_group_gid", return_value=None
    ):

        result = add_user_to_docker_group("sentinel")

    assert result["success"] is False
    assert "no group to fall back on" in result["error"]


def test_add_user_to_docker_group_reports_usermod_failure_when_no_fallback_possible():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": False, "error": "exit code 1"}
    ), patch(
        "installer.docker_setup._user_in_docker_group", return_value=False
    ), patch(
        "installer.docker_setup._docker_group_gid", return_value=None
    ):

        result = add_user_to_docker_group("sentinel")

    assert result == {"success": False, "error": "exit code 1"}


def test_add_user_to_docker_group_fallback_itself_fails_cleanly():

    with patch(
        "installer.docker_setup.run_privileged",
        side_effect=[
            {"success": True, "error": None},   # usermod (silently no-ops)
            {"success": True, "error": None},   # ensure_entry
            {"success": False, "error": "exit code 1"}   # gpasswd
        ]
    ), patch(
        "installer.docker_setup._user_in_docker_group", return_value=False
    ), patch(
        "installer.docker_setup._docker_group_gid", return_value="958"
    ):

        result = add_user_to_docker_group("sentinel")

    assert result == {"success": False, "error": "exit code 1"}


def test_add_user_to_docker_group_fallback_reports_still_not_member_if_gpasswd_lies_too():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ), patch(
        "installer.docker_setup._user_in_docker_group", return_value=False
    ), patch(
        "installer.docker_setup._docker_group_gid", return_value="958"
    ):

        result = add_user_to_docker_group("sentinel")

    assert result["success"] is False
    assert "still isn't a real member" in result["error"]


def test_user_in_docker_group_parses_real_id_output():

    with patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="sentinel wheel docker\n")
    ):

        assert _user_in_docker_group("sentinel") is True


def test_user_in_docker_group_false_when_absent():

    with patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="sentinel wheel\n")
    ):

        assert _user_in_docker_group("sentinel") is False


def test_docker_group_gid_parses_real_getent_output():

    with patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="docker:x:958:\n")
    ):

        assert _docker_group_gid() == "958"


def test_docker_group_gid_none_when_group_absent():

    with patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=1, stdout="")
    ):

        assert _docker_group_gid() is None


def test_start_docker_service_calls_systemctl():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run:

        result = start_docker_service()

    assert result == {"success": True, "error": None}
    mock_run.assert_called_once_with(
        ["systemctl", "enable", "--now", "docker"]
    )


def test_run_docker_command_plain_when_no_workaround_needed():

    with patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=0)
    ) as mock_run:

        run_docker_command(["docker", "ps"])

    mock_run.assert_called_once_with(["docker", "ps"])


def test_run_docker_command_uses_sg_when_workaround_needed_and_available():

    with patch(
        "installer.docker_setup.shutil.which", return_value="/usr/bin/sg"
    ), patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=0)
    ) as mock_run:

        run_docker_command(
            ["docker", "compose", "-f", "my compose.yml", "up", "-d"],
            use_group_workaround=True
        )

    mock_run.assert_called_once_with(
        [
            "sg", "docker", "-c",
            "docker compose -f 'my compose.yml' up -d"
        ]
    )


def test_run_docker_command_falls_back_to_sudo_when_sg_missing():

    with patch(
        "installer.docker_setup.shutil.which", return_value=None
    ), patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=0)
    ) as mock_run:

        run_docker_command(["docker", "ps"], use_group_workaround=True)

    mock_run.assert_called_once_with(["sudo", "docker", "ps"])
