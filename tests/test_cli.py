from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from installer.cli import app
from installer.detect import GpuInfo, SystemInfo


runner = CliRunner()


def make_system_info(**overrides) -> SystemInfo:

    base = dict(
        cpu_cores_physical=6,
        cpu_cores_logical=12,
        cpu_model="Test CPU",
        ram_total_gb=32.0,
        disk_free_gb=900.0,
        disk_path_checked="/",
        gpus=[],
        docker_installed=True,
        docker_running=True,
        docker_compose_v2=True,
        architecture="x86_64",
        os_id="fedora",
        os_pretty_name="Fedora Linux 44",
        os_is_atomic=False
    )

    base.update(overrides)

    return SystemInfo(**base)


READY_WRITE_RESULT = {
    "success": True,
    "compose_path": "/scratch/stack/docker-compose.yml",
    "warnings": []
}


def test_urls_shell_prints_real_service_urls_from_saved_state(tmp_path):

    previous_state = {
        "tier": "medium",
        "puid": 1000,
        "pgid": 1000,
        "gpu_vendor": "nvidia",
        "enabled_optional": [],
    }

    with patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.load_previous_state", return_value=previous_state
    ), patch(
        "installer.cli.detect_host_ip", return_value="192.168.1.50"
    ):

        result = runner.invoke(app, ["urls"])

    assert result.exit_code == 0, result.output
    assert "http://192.168.1.50" in result.output


def test_urls_shell_prints_nothing_with_no_previous_state(tmp_path):

    with patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.load_previous_state", return_value=None
    ):

        result = runner.invoke(app, ["urls"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == ""


def test_no_gpu_exits_1_with_explanation():

    with patch("installer.cli.detect_system", return_value=make_system_info()):

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 1
    assert "No dedicated GPU" in result.output


def test_docker_not_installed_declined_exits_1():

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)],
        docker_installed=False,
        docker_running=False,
        docker_compose_v2=False
    )

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.install_plan_for",
        return_value={"method": "get.docker.com", "description": "curl ... | sh", "needs_reboot": False}
    ), patch("installer.cli.install_docker") as mock_install:

        result = runner.invoke(app, ["--plain"], input="n\n")

    assert result.exit_code == 1
    assert "Docker is required" in result.output
    mock_install.assert_not_called()


def test_docker_not_installed_unsupported_distro_exits_1():

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)],
        docker_installed=False,
        docker_running=False,
        docker_compose_v2=False,
        os_id="gentoo"
    )

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.install_plan_for", return_value=None
    ):

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 1
    assert "No known automatic install method" in result.output


def test_docker_not_installed_non_interactive_installs_and_continues(tmp_path):
    """
    The real behavior change this session is about: a missing Docker
    no longer just prints a link and exits - it's installed (assisted)
    and the run continues, exactly like a host that already had it.
    """

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)],
        docker_installed=False,
        docker_running=False,
        docker_compose_v2=False
    )

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.install_plan_for",
        return_value={"method": "get.docker.com", "description": "curl ... | sh", "needs_reboot": False}
    ), patch(
        "installer.cli.install_docker",
        return_value={"success": True, "error": None, "method": "get.docker.com", "needs_reboot": False}
    ) as mock_install, patch(
        "installer.cli.start_docker_service", return_value={"success": True, "error": None}
    ) as mock_start, patch(
        "installer.cli.add_user_to_docker_group", return_value={"success": True, "error": None}
    ) as mock_group, patch(
        "installer.cli.ensure_compose_v2", return_value={"success": True, "error": None}
    ), patch(
        "installer.cli.detect_docker",
        return_value={"docker_installed": True, "docker_running": False, "docker_compose_v2": True}
    ), patch(
        "installer.cli.check_docker_ready",
        return_value={"docker_running": True, "docker_compose_v2": True}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ):

        result = runner.invoke(app, ["--non-interactive", "--yes", "--no-start"])

    assert result.exit_code == 0, result.output
    assert "Docker is ready" in result.output
    mock_install.assert_called_once_with("fedora", False)
    mock_start.assert_called_once()
    mock_group.assert_called_once()


def test_docker_install_failure_exits_1():

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)],
        docker_installed=False,
        docker_running=False,
        docker_compose_v2=False
    )

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.install_plan_for",
        return_value={"method": "get.docker.com", "description": "curl ... | sh", "needs_reboot": False}
    ), patch(
        "installer.cli.install_docker",
        return_value={"success": False, "error": "curl: connection refused", "method": "get.docker.com", "needs_reboot": False}
    ):

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 1
    assert "Docker install failed" in result.output


def test_docker_not_installed_atomic_host_prints_reboot_instructions():
    """
    The real gap found against a real Bazzite GPU host: rpm-ostree
    layering doesn't take effect live. A successful atomic install
    must exit cleanly (0, not an error) with real reboot instructions,
    not silently pretend Docker is ready.
    """

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 2080", vram_total_mb=8192)],
        docker_installed=False,
        docker_running=False,
        docker_compose_v2=False,
        os_id="bazzite",
        os_is_atomic=True
    )

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.install_plan_for",
        return_value={
            "method": "rpm-ostree",
            "description": "rpm-ostree install docker-ce ... (needs a reboot)",
            "needs_reboot": True
        }
    ), patch(
        "installer.cli.install_docker",
        return_value={"success": True, "error": None, "method": "rpm-ostree", "needs_reboot": True}
    ) as mock_install, patch(
        "installer.cli.start_docker_service"
    ) as mock_start:

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 0, result.output
    assert "reboot" in result.output.lower()
    mock_install.assert_called_once_with("bazzite", True)
    mock_start.assert_not_called()


def test_docker_running_false_non_interactive_starts_service(tmp_path):

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)],
        docker_running=False
    )

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.start_docker_service", return_value={"success": True, "error": None}
    ) as mock_start, patch(
        "installer.cli.add_user_to_docker_group", return_value={"success": True, "error": None}
    ) as mock_group, patch(
        "installer.cli.detect_docker",
        return_value={"docker_installed": True, "docker_running": False, "docker_compose_v2": True}
    ), patch(
        "installer.cli.check_docker_ready",
        return_value={"docker_running": True, "docker_compose_v2": True}
    ) as mock_ready, patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ):

        result = runner.invoke(app, ["--non-interactive", "--yes", "--no-start"])

    assert result.exit_code == 0, result.output
    mock_start.assert_called_once()
    mock_group.assert_called_once()
    mock_ready.assert_called_once_with(use_group_workaround=True)


def test_docker_running_false_group_add_real_gap_regression():
    """
    The exact bug found live against msi-laptop: Docker installed by a
    previous run (the atomic-OS reboot-split case) never got its user
    added to the docker group, since group-adding only happened
    alongside a *fresh* install. The daemon started cleanly
    (docker_installed/docker_running both real per systemd), but this
    user's own `docker info` failed with a genuine permission error
    against docker.sock (root:docker) - not a "not running" problem.
    A plain detect_docker() re-check inherits this process's own stale
    group list even after usermod -aG runs, so the fix must route
    through check_docker_ready(use_group_workaround=True), not a plain
    detect_docker() call, or this exact failure reproduces.
    """

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)],
        docker_running=False
    )

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.start_docker_service", return_value={"success": True, "error": None}
    ), patch(
        "installer.cli.add_user_to_docker_group", return_value={"success": True, "error": None}
    ), patch(
        # detect_docker() itself still reports "not running" - it has
        # no group workaround, matching the real failure exactly.
        "installer.cli.detect_docker",
        return_value={"docker_installed": True, "docker_running": False, "docker_compose_v2": True}
    ), patch(
        "installer.cli.check_docker_ready",
        return_value={"docker_running": True, "docker_compose_v2": True}
    ):

        result = runner.invoke(app, ["--non-interactive", "--yes", "--no-start"])

    assert result.exit_code == 0, result.output
    assert "still isn't ready" not in result.output


def test_docker_still_not_ready_after_assist_exits_1(tmp_path):
    """
    A real fix attempt that doesn't actually resolve the problem
    (e.g. the service refuses to start for a reason outside Anvil's
    control) must be reported honestly, not treated as success.
    """

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)],
        docker_running=False
    )

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.start_docker_service", return_value={"success": True, "error": None}
    ), patch(
        "installer.cli.add_user_to_docker_group", return_value={"success": True, "error": None}
    ), patch(
        "installer.cli.detect_docker",
        return_value={"docker_installed": True, "docker_running": False, "docker_compose_v2": True}
    ), patch(
        "installer.cli.check_docker_ready",
        return_value={"docker_running": False, "docker_compose_v2": True}
    ):

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 1
    assert "still isn't ready" in result.output


def test_non_interactive_without_yes_exits_1():

    result = runner.invoke(app, ["--non-interactive"])

    assert result.exit_code == 1
    assert "--yes is required" in result.output


def test_non_interactive_medium_gpu_writes_stack_without_comfyui(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)])

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(app, ["--non-interactive", "--yes", "--no-start"])

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "medium"
    assert config.enabled_optional == set()


def test_non_interactive_heavy_nvidia_with_comfyui_flag_enables_it(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)])

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app, ["--non-interactive", "--yes", "--no-start", "--comfyui"]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "heavy"
    # invokeai is also NVIDIA-supported and real like comfyui, so a
    # fresh non-interactive run defaults it on too - not requested via
    # flag here, just the same "supported hardware defaults on" rule.
    assert config.enabled_optional == {"comfyui", "invokeai"}


def test_non_interactive_heavy_amd_defaults_comfyui_on(tmp_path):
    """
    AMD has a real, verified ComfyUI image now (corundex/comfyui-rocm)
    - a fresh non-interactive run defaults it on, matching NVIDIA's
    own default-on behavior, since it's real, verified, and supported.
    """

    info = make_system_info(gpus=[GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480)])

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(app, ["--non-interactive", "--yes", "--no-start"])

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    # invokeai also has a real, official AMD image - defaults on too.
    assert config.enabled_optional == {"comfyui", "invokeai"}


def test_non_interactive_heavy_intel_defaults_comfyui_on(tmp_path):
    """
    Intel Arc has a real, verified ComfyUI image now
    (yanwk/comfyui-boot:xpu) - a fresh non-interactive run defaults it
    on, matching NVIDIA/AMD's own default-on behavior.
    """

    info = make_system_info(gpus=[GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384)])

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(app, ["--non-interactive", "--yes", "--no-start"])

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"comfyui"}


def test_non_interactive_heavy_intel_never_enables_invokeai(tmp_path):
    """
    Unlike ComfyUI, InvokeAI has no official Intel Arc image - a real,
    currently-live gap. A fresh non-interactive run on Intel Arc must
    never default it on, unlike NVIDIA/AMD above.
    """

    info = make_system_info(gpus=[GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384)])

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(app, ["--non-interactive", "--yes", "--no-start"])

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"comfyui"}
    assert "invokeai" not in config.enabled_optional


def test_non_interactive_heavy_amd_with_no_invokeai_flag_disables_it(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480)])

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app, ["--non-interactive", "--yes", "--no-start", "--no-invokeai"]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"comfyui"}


def test_non_interactive_rerun_reuses_previous_tier_and_comfyui_choice(tmp_path):
    """
    Real regression lock for a bug caught while building this: a
    previous .anvil-state.json on disk must be read from the same
    STACK_DIR the rest of the command uses, not silently ignored -
    caught by a leftover real stack/ directory bleeding into an
    earlier version of this test before STACK_DIR was mocked here.
    """

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / ".anvil-state.json").write_text(
        '{"tier": "heavy", "puid": 1000, "pgid": 1000, "gpu_vendor": "nvidia", '
        '"enabled_optional": ["comfyui"], "generated_at": "2026-01-01T00:00:00+00:00"}'
    )

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)])

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", stack_dir
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(app, ["--non-interactive", "--yes", "--no-start"])

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "heavy"
    assert config.enabled_optional == {"comfyui"}


def test_confirm_declined_aborts(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)])

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack"
    ) as mock_write_stack:

        result = runner.invoke(
            app, ["--plain", "--puid", "1000", "--pgid", "1000", "--no-start"], input="light\nn\n"
        )

    assert result.exit_code == 0
    assert "Aborted" in result.output
    mock_write_stack.assert_not_called()


def test_start_success_prints_service_urls(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)])
    up_proc = MagicMock(returncode=0)

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available", return_value={"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}}
    ), patch(
        "installer.cli.verify_stack_running",
        return_value={"all_running": True, "error": None, "not_running": []}
    ), patch(
        "installer.cli.run_docker_command", return_value=up_proc
    ) as mock_run_docker:

        result = runner.invoke(app, ["--non-interactive", "--yes", "--start"])

    assert result.exit_code == 0, result.output
    assert "Dashboard" in result.output
    assert "Ollama API" in result.output
    assert "Open WebUI" in result.output
    mock_run_docker.assert_called_once()


def test_fresh_docker_install_uses_group_workaround_on_start(tmp_path):
    """
    A user added to the docker group in this same run has a stale
    cached group list in this same process - the final `docker compose
    up` must route through the sg-based workaround (see
    docker_setup.run_docker_command), not plain sudo/no-sudo, or it'll
    fail with a permission error despite the group add having "worked."
    """

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)],
        docker_installed=False,
        docker_running=False,
        docker_compose_v2=False
    )
    up_proc = MagicMock(returncode=0)

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.install_plan_for",
        return_value={"method": "get.docker.com", "description": "curl ... | sh", "needs_reboot": False}
    ), patch(
        "installer.cli.install_docker",
        return_value={"success": True, "error": None, "method": "get.docker.com", "needs_reboot": False}
    ), patch(
        "installer.cli.start_docker_service", return_value={"success": True, "error": None}
    ), patch(
        "installer.cli.add_user_to_docker_group", return_value={"success": True, "error": None}
    ), patch(
        "installer.cli.ensure_compose_v2", return_value={"success": True, "error": None}
    ), patch(
        "installer.cli.detect_docker",
        return_value={"docker_installed": True, "docker_running": False, "docker_compose_v2": True}
    ), patch(
        "installer.cli.check_docker_ready",
        return_value={"docker_running": True, "docker_compose_v2": True}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available", return_value={"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}}
    ), patch(
        "installer.cli.verify_stack_running",
        return_value={"all_running": True, "error": None, "not_running": []}
    ), patch(
        "installer.cli.run_docker_command", return_value=up_proc
    ) as mock_run_docker:

        result = runner.invoke(app, ["--non-interactive", "--yes", "--start"])

    assert result.exit_code == 0, result.output
    mock_run_docker.assert_called_once_with(
        ["docker", "compose", "-f", READY_WRITE_RESULT["compose_path"], "up", "-d"],
        use_group_workaround=True
    )


def test_start_failure_exits_1(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)])
    up_proc = MagicMock(returncode=1)

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available", return_value={"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}}
    ), patch(
        "installer.cli.run_docker_command", return_value=up_proc
    ):

        result = runner.invoke(app, ["--non-interactive", "--yes", "--start"])

    assert result.exit_code == 1
    assert "Failed to start" in result.output


def test_interactive_start_own_orphan_cleans_up_and_retries(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)])
    up_proc = MagicMock(returncode=0)

    conflict_then_clear = [
        {
            "available": False,
            "conflicts": [11434],
            "owners": {11434: 'your own orphaned containers from a previous stack (project "stack")'},
            "port_services": {11434: "ollama"},
            "own_orphan": {11434: True},
        },
        {"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}},
    ]

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available", side_effect=conflict_then_clear
    ), patch(
        "installer.cli.remove_orphaned_containers", return_value={"success": True, "error": None}
    ) as mock_cleanup, patch(
        "installer.cli.verify_stack_running",
        return_value={"all_running": True, "error": None, "not_running": []}
    ), patch(
        "installer.cli.run_docker_command", return_value=up_proc
    ):

        result = runner.invoke(
            app,
            ["--plain", "--yes", "--tier", "medium", "--puid", "1000", "--pgid", "1000"],
            input="y\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Stack is up" in result.output
    mock_cleanup.assert_called_once_with("stack")


def test_interactive_start_remaps_port_and_retries(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)])
    up_proc = MagicMock(returncode=0)

    conflict_then_clear = [
        {
            "available": False,
            "conflicts": [11434],
            "owners": {11434: None},
            "port_services": {11434: "ollama"},
            "own_orphan": {11434: False},
        },
        {"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}},
    ]

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack, patch(
        "installer.cli.check_ports_available", side_effect=conflict_then_clear
    ), patch(
        "installer.cli.verify_stack_running",
        return_value={"all_running": True, "error": None, "not_running": []}
    ), patch(
        "installer.cli.run_docker_command", return_value=up_proc
    ):

        result = runner.invoke(
            app,
            ["--plain", "--yes", "--tier", "medium", "--puid", "1000", "--pgid", "1000"],
            input="y\n11500\n"
        )

    assert result.exit_code == 0, result.output
    assert "Stack is up" in result.output

    # First call is the initial generate; the second is the post-remap
    # regenerate, and must carry the new port through port_overrides.
    assert mock_write_stack.call_count == 2
    regenerated_config = mock_write_stack.call_args_list[1][0][0]
    assert regenerated_config.port_overrides == {"ollama": 11500}


def test_interactive_start_port_conflict_give_up_exits_1(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)])

    always_conflicted = {
        "available": False,
        "conflicts": [80],
        "owners": {80: None},
        "port_services": {80: "traefik"},
        "own_orphan": {80: False},
    }

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available", return_value=always_conflicted
    ), patch(
        "installer.cli.run_docker_command"
    ) as mock_run_docker:

        result = runner.invoke(
            app,
            ["--plain", "--yes", "--tier", "medium", "--puid", "1000", "--pgid", "1000"],
            input="y\n"
        )

    assert result.exit_code == 1
    assert "can't be remapped automatically" in result.output
    mock_run_docker.assert_not_called()
