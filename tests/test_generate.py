from unittest.mock import patch

from installer.detect import GpuInfo
from installer.generate import GenerationConfig, load_previous_state, save_state, write_stack
from installer.tiers import TIERS


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
    assert result["warnings"] == [
        "Open WebUI and ComfyUI don't wire themselves together automatically - in "
        "Open WebUI, go to Admin Panel > Settings > Images, enable Image Generation, "
        "set the engine to ComfyUI, and point it at http://comfyui:8188, then click "
        "Verify Connection."
    ]


def test_write_stack_heavy_amd_with_comfyui_requested_warns_and_omits(tmp_path):

    config = make_config(
        "heavy",
        gpu=GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480),
        enabled_optional={"comfyui"}
    )
    result = write_stack(config, output_dir=tmp_path / "stack")

    compose = (tmp_path / "stack" / "docker-compose.yml").read_text()

    assert "comfyui:" not in compose
    assert any("NVIDIA-only" in warning for warning in result["warnings"])


def test_write_stack_creates_data_directories_only_for_enabled_services(tmp_path):

    config = make_config("medium", gpu=GpuInfo(vendor="nvidia", name="fake", vram_total_mb=8192))
    write_stack(config, output_dir=tmp_path / "stack")

    assert (tmp_path / "stack" / "data" / "ollama").is_dir()
    assert (tmp_path / "stack" / "data" / "open-webui").is_dir()
    assert not (tmp_path / "stack" / "data" / "comfyui").exists()


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
