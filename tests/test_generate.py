from unittest.mock import patch

import pytest

from installer.detect import GpuInfo
from installer.generate import GenerationConfig, load_previous_state, resolve_ports, save_state, write_stack
from installer.tiers import TIERS


@pytest.fixture(autouse=True)
def no_real_port_conflicts():
    """
    write_stack() now does a real TCP connect per enabled service's
    port (port_in_use()) - hermetic by default here so a real ambient
    service on the machine running these tests (this dev machine has a
    genuine native Ollama on 11434) can't leak into unrelated test
    assertions. Tests that actually exercise port-conflict behavior
    override this with their own nested patch.
    """

    with patch("installer.generate.port_in_use", return_value=False):
        yield


def make_config(tier_name, gpu=None, enabled_optional=None):

    return GenerationConfig(
        tier=TIERS[tier_name],
        puid=1000,
        pgid=1000,
        gpu=gpu,
        enabled_optional=enabled_optional or set()
    )


def test_write_stack_light_tier_no_gpu_renders_ollama_and_open_webui(tmp_path):

    config = make_config("light")
    result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "ollama:" in compose
    assert "open-webui:" in compose
    assert "comfyui:" not in compose
    assert result["success"] is True


def test_write_stack_nvidia_uses_gpu_reservation_not_amd_devices(tmp_path):

    config = make_config("medium", gpu=GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192))
    write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "driver: nvidia" in compose
    assert "/dev/kfd" not in compose
    assert "ollama/ollama:rocm" not in compose


def test_write_stack_amd_uses_dev_kfd_devices_not_gpu_reservation(tmp_path):

    with patch("installer.generate.detect_render_group_gid", return_value=44):

        config = make_config("medium", gpu=GpuInfo(vendor="amd", name="RX 6800", vram_total_mb=16384))
        write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "/dev/kfd" in compose
    assert "/dev/dri" in compose
    assert "ollama/ollama:rocm" in compose
    assert "driver: nvidia" not in compose
    assert 'group_add' in compose and '"44"' in compose


def test_write_stack_heavy_nvidia_with_comfyui_requested_includes_it(tmp_path):

    config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
        enabled_optional={"comfyui"}
    )
    result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "comfyui:" in compose
    assert "mmartial/comfyui-nvidia-docker" in compose
    assert (
        "Open WebUI and ComfyUI don't wire themselves together automatically - in "
        "Open WebUI, go to Admin Panel > Settings > Images, enable Image Generation, "
        "set the engine to ComfyUI, and point it at http://comfyui:8188, then click "
        "Verify Connection."
    ) in result["warnings"]
    assert any("NVIDIA Container Toolkit" in warning for warning in result["warnings"])


def test_write_stack_heavy_amd_with_comfyui_requested_renders_rocm_image(tmp_path):

    with patch("installer.generate.detect_render_group_gid", return_value=44):

        config = make_config(
            "heavy",
            gpu=GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480),
            enabled_optional={"comfyui"}
        )
        result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "comfyui:" in compose
    assert "corundex/comfyui-rocm" in compose
    assert "/dev/kfd" in compose
    assert "mmartial/comfyui-nvidia-docker" not in compose
    assert not any("was requested but skipped" in warning for warning in result["warnings"])


def test_write_stack_heavy_amd_with_comfyui_warns_about_missing_manager(tmp_path):
    """
    Real, vendor-specific gap: unlike NVIDIA's and Intel's images, the
    AMD ComfyUI image doesn't bundle ComfyUI-Manager - confirmed by
    reading each image's own docs. Not auto-fixed (would need git and
    network access at generate time, plus a pip install step that only
    makes sense once the container exists), so this is a warning with
    the real fix commands, not a silent no-op.
    """

    with patch("installer.generate.detect_render_group_gid", return_value=44):

        config = make_config(
            "heavy",
            gpu=GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480),
            enabled_optional={"comfyui"}
        )
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert any(
        "ComfyUI-Manager" in warning and "pip install" in warning
        for warning in result["warnings"]
    )


def test_write_stack_heavy_nvidia_and_intel_never_warn_about_comfyui_manager(tmp_path):

    nvidia_config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
        enabled_optional={"comfyui"}
    )
    nvidia_result = write_stack(nvidia_config, output_dir=tmp_path / "nvidia-stack")

    intel_config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384),
        enabled_optional={"comfyui"}
    )
    intel_result = write_stack(intel_config, output_dir=tmp_path / "intel-stack")

    assert not any("ComfyUI-Manager" in warning for warning in nvidia_result["warnings"])
    assert not any("ComfyUI-Manager" in warning for warning in intel_result["warnings"])


def test_write_stack_heavy_intel_with_comfyui_requested_renders_xpu_image(tmp_path):

    config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384),
        enabled_optional={"comfyui"}
    )
    result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "comfyui:" in compose
    assert "yanwk/comfyui-boot:xpu" in compose
    assert "/dev/dri" in compose
    assert "ipc: host" in compose
    assert not any("was requested but skipped" in warning for warning in result["warnings"])


def test_write_stack_heavy_no_gpu_with_comfyui_requested_warns_and_omits(tmp_path):

    config = make_config("heavy", gpu=None, enabled_optional={"comfyui"})
    result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "comfyui:" not in compose
    assert any("was requested but skipped" in warning for warning in result["warnings"])


def test_write_stack_nvidia_warns_about_container_toolkit(tmp_path):

    config = make_config("medium", gpu=GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192))
    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any(
        "docs.nvidia.com/datacenter/cloud-native/container-toolkit" in warning
        for warning in result["warnings"]
    )


def test_write_stack_amd_never_warns_about_container_toolkit(tmp_path):
    """
    A real, deliberate asymmetry, not an oversight: detect_amd_gpus()
    only ever succeeds when the amdgpu kernel driver is already
    loaded (that's the mechanism it reads VRAM through), unlike
    nvidia-smi, which works standalone independent of whether the
    separate NVIDIA Container Toolkit is installed - so AMD has
    nothing equivalent left to warn about.
    """

    config = make_config("medium", gpu=GpuInfo(vendor="amd", name="RX 6800", vram_total_mb=16384))
    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("Toolkit" in warning or "driver" in warning for warning in result["warnings"])


def test_write_stack_no_gpu_produces_no_toolkit_warning(tmp_path):

    config = make_config("light", gpu=None)
    result = write_stack(config, output_dir=tmp_path / "stack")

    assert result["warnings"] == []


def test_write_stack_heavy_nvidia_with_invokeai_requested_includes_it(tmp_path):

    config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
        enabled_optional={"invokeai"}
    )
    result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "invokeai:" in compose
    assert "ghcr.io/invoke-ai/invokeai:latest" in compose
    assert "CONTAINER_UID=1000" in compose
    assert not any("AMD Container Toolkit" in warning for warning in result["warnings"])


def test_write_stack_heavy_amd_with_invokeai_requested_renders_rocm_image_and_runtime(tmp_path):
    """
    A real, InvokeAI-specific mechanism, confirmed against InvokeAI's
    own real docker-compose.yml (fetched directly, not summarized):
    `runtime: amd` + AMD_VISIBLE_DEVICES, not the plain /dev/kfd +
    /dev/dri passthrough Ollama/ComfyUI's AMD blocks use.
    """

    with patch("installer.generate.detect_render_group_gid", return_value=44):

        config = make_config(
            "heavy",
            gpu=GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480),
            enabled_optional={"invokeai"}
        )
        result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "invokeai:" in compose
    assert "ghcr.io/invoke-ai/invokeai:main-rocm" in compose
    assert "runtime: amd" in compose
    assert "AMD_VISIBLE_DEVICES=all" in compose
    assert 'RENDER_GROUP_ID=44' in compose
    assert not any("was requested but skipped" in warning for warning in result["warnings"])
    assert any(
        "AMD Container Toolkit" in warning and "instinct.docs.amd.com" in warning
        for warning in result["warnings"]
    )


def test_write_stack_heavy_nvidia_never_warns_about_amd_container_toolkit(tmp_path):

    config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
        enabled_optional={"invokeai"}
    )
    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("AMD Container Toolkit" in warning for warning in result["warnings"])


def test_write_stack_heavy_amd_without_invokeai_never_warns_about_amd_container_toolkit(tmp_path):

    with patch("installer.generate.detect_render_group_gid", return_value=44):

        config = make_config(
            "heavy",
            gpu=GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480),
            enabled_optional={"comfyui"}
        )
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("AMD Container Toolkit" in warning for warning in result["warnings"])


def test_write_stack_heavy_intel_with_invokeai_requested_warns_and_omits(tmp_path):
    """
    Unlike ComfyUI, InvokeAI has no official Intel Arc image at all -
    a real, currently-live gap, not a defensive/unreachable case.
    """

    config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384),
        enabled_optional={"invokeai"}
    )
    result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "invokeai:" not in compose
    assert any(
        "InvokeAI was requested but skipped" in warning and "Intel Arc has none" in warning
        for warning in result["warnings"]
    )


def test_write_stack_heavy_no_gpu_with_invokeai_requested_warns_and_omits(tmp_path):

    config = make_config("heavy", gpu=None, enabled_optional={"invokeai"})
    result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "invokeai:" not in compose
    assert any("InvokeAI was requested but skipped" in warning for warning in result["warnings"])


def test_write_stack_invokeai_port_in_use_warns_generically(tmp_path):

    config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
        enabled_optional={"invokeai"}
    )

    with patch("installer.generate.port_in_use", side_effect=lambda port: port == 9090):
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert any(
        "Port 9090" in warning and "invokeai container will fail to bind" in warning
        for warning in result["warnings"]
    )


def test_write_stack_creates_data_directories_only_for_enabled_services(tmp_path):

    config = make_config("medium", gpu=GpuInfo(vendor="nvidia", name="fake", vram_total_mb=8192))
    write_stack(config, output_dir=tmp_path / "stack")

    assert (tmp_path / "stack" / "data" / "ollama").is_dir()
    assert (tmp_path / "stack" / "data" / "open-webui").is_dir()
    assert not (tmp_path / "stack" / "data" / "comfyui").exists()
    assert not (tmp_path / "stack" / "data" / "invokeai").exists()


def test_save_and_load_previous_state_round_trips(tmp_path):

    config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
        enabled_optional={"comfyui"}
    )

    output_dir = tmp_path / "stack"
    output_dir.mkdir()
    save_state(config, output_dir)

    state = load_previous_state(output_dir)

    assert state["tier"] == "heavy"
    assert state["puid"] == 1000
    assert state["gpu_vendor"] == "nvidia"
    assert state["enabled_optional"] == ["comfyui"]


def test_load_previous_state_missing_file_returns_none(tmp_path):
    assert load_previous_state(tmp_path) is None


def test_write_stack_ollama_port_in_use_warns_with_native_install_guidance(tmp_path):

    config = make_config("light")

    with patch("installer.generate.port_in_use", side_effect=lambda port: port == 11434):
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert any(
        "Port 11434" in warning and "systemctl status ollama" in warning
        for warning in result["warnings"]
    )


def test_write_stack_comfyui_port_in_use_warns_generically(tmp_path):

    config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
        enabled_optional={"comfyui"}
    )

    with patch("installer.generate.port_in_use", side_effect=lambda port: port == 8188):
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert any(
        "Port 8188" in warning and "comfyui container will fail to bind" in warning
        for warning in result["warnings"]
    )


def test_write_stack_no_port_conflicts_produces_no_port_warning(tmp_path):

    config = make_config("light")

    with patch("installer.generate.port_in_use", return_value=False):
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("Port" in warning for warning in result["warnings"])


def test_write_stack_dashboard_port_conflict_warns(tmp_path):

    config = make_config("light")

    with patch("installer.generate.port_in_use", side_effect=lambda port: port == 8080):
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert any(
        "Port 8080" in warning and "dashboard container will fail to bind" in warning
        for warning in result["warnings"]
    )


def test_write_stack_always_renders_dashboard_service(tmp_path):
    """
    Unlike ollama/open-webui/comfyui, the dashboard isn't a tiers.py
    ServiceDefinition - it's not user-choosable or tier-gated, so it
    should render for every tier, GPU or not.
    """

    for tier_name in ("light", "medium", "heavy"):

        config = make_config(tier_name)
        write_stack(config, output_dir=tmp_path / tier_name)

        compose = (tmp_path / tier_name / "docker-compose.yml").read_text()

        assert "dashboard:" in compose
        assert "nginx:alpine" in compose
        assert '"8080:80"' in compose


def test_write_stack_writes_dashboard_index_html(tmp_path):

    config = make_config("light")
    write_stack(config, output_dir=tmp_path / "stack")

    index_html = (tmp_path / "stack" / "dashboard" / "index.html").read_text()

    assert "<html" in index_html
    assert "Open WebUI" in index_html


def test_dashboard_links_reflect_enabled_services_and_use_detected_host(tmp_path):

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):

        light_config = make_config("light")
        write_stack(light_config, output_dir=tmp_path / "light-stack")
        light_html = (tmp_path / "light-stack" / "dashboard" / "index.html").read_text()

        heavy_config = make_config(
            "heavy",
            gpu=GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
            enabled_optional={"comfyui"}
        )
        write_stack(heavy_config, output_dir=tmp_path / "heavy-stack")
        heavy_html = (tmp_path / "heavy-stack" / "dashboard" / "index.html").read_text()

    assert "http://192.168.1.50:3000" in light_html
    assert "http://192.168.1.50:11434" in light_html
    assert "http://192.168.1.50:8188" not in light_html

    assert "http://192.168.1.50:8188" in heavy_html


def test_dashboard_falls_back_to_localhost_when_host_ip_undetected(tmp_path):

    with patch("installer.generate.detect_host_ip", return_value=None):

        config = make_config("light")
        write_stack(config, output_dir=tmp_path / "stack")

    index_html = (tmp_path / "stack" / "dashboard" / "index.html").read_text()

    assert "http://localhost:3000" in index_html


def test_resolve_ports_returns_defaults_when_no_overrides():

    config = make_config("light")
    ports = resolve_ports(config)

    assert ports["ollama"] == 11434
    assert ports["open-webui"] == 3000
    assert ports["comfyui"] == 8188
    assert ports["invokeai"] == 9090
    assert ports["dashboard"] == 8080


def test_resolve_ports_applies_overrides():

    config = make_config("light")
    config.port_overrides = {"ollama": 11435, "dashboard": 8081}
    ports = resolve_ports(config)

    assert ports["ollama"] == 11435
    assert ports["dashboard"] == 8081
    assert ports["open-webui"] == 3000


def test_write_stack_with_port_overrides_renders_remapped_port(tmp_path):

    config = make_config("light")
    config.port_overrides = {"ollama": 11435}
    write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert '"11435:11434"' in compose
    assert '"11434:11434"' not in compose


def test_write_stack_with_port_overrides_dashboard_remapped(tmp_path):

    config = make_config("light")
    config.port_overrides = {"dashboard": 9000}
    write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert '"9000:80"' in compose
    assert '"8080:80"' not in compose
