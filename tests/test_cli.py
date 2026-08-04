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
        os_pretty_name="Fedora Linux 44"
    )

    base.update(overrides)

    return SystemInfo(**base)


READY_WRITE_RESULT = {
    "success": True,
    "compose_path": "/scratch/stack/docker-compose.yml",
    "warnings": []
}


def test_no_gpu_exits_1_with_explanation():

    with patch("installer.cli.detect_system", return_value=make_system_info()):

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 1
    assert "No dedicated GPU" in result.output


def test_docker_not_ready_exits_1():

    info = make_system_info(
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)],
        docker_running=False
    )

    with patch("installer.cli.detect_system", return_value=info):

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 1
    assert "Docker" in result.output


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
    assert config.enabled_optional == {"comfyui"}


def test_non_interactive_heavy_amd_defaults_comfyui_off(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480)])

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(app, ["--non-interactive", "--yes", "--no-start"])

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == set()


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
        "installer.cli.run_docker_command", return_value=up_proc
    ) as mock_run_docker:

        result = runner.invoke(app, ["--non-interactive", "--yes", "--start"])

    assert result.exit_code == 0, result.output
    assert "Ollama API" in result.output
    assert "Open WebUI" in result.output
    mock_run_docker.assert_called_once()


def test_start_failure_exits_1(tmp_path):

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)])
    up_proc = MagicMock(returncode=1)

    with patch("installer.cli.detect_system", return_value=info), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.run_docker_command", return_value=up_proc
    ):

        result = runner.invoke(app, ["--non-interactive", "--yes", "--start"])

    assert result.exit_code == 1
    assert "Failed to start" in result.output
