from installer.detect import GpuInfo
from installer.tiers import TIERS, enabled_service_keys, recommend_tier


def test_recommend_tier_no_gpu_returns_no_tier():

    result = recommend_tier(None)

    assert result.tier is None
    assert "No dedicated GPU" in result.explanation


def test_recommend_tier_below_8gb_recommends_light():

    gpu = GpuInfo(vendor="nvidia", name="GTX 1650", vram_total_mb=4096)
    result = recommend_tier(gpu)

    assert result.tier.name == "light"


def test_recommend_tier_8gb_recommends_medium():

    gpu = GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)
    result = recommend_tier(gpu)

    assert result.tier.name == "medium"


def test_recommend_tier_just_below_medium_threshold_stays_light():

    gpu = GpuInfo(vendor="nvidia", name="fake", vram_total_mb=8191)
    result = recommend_tier(gpu)

    assert result.tier.name == "light"


def test_recommend_tier_12gb_recommends_heavy():

    gpu = GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)
    result = recommend_tier(gpu)

    assert result.tier.name == "heavy"


def test_enabled_service_keys_light_and_medium_never_include_comfyui():

    gpu = GpuInfo(vendor="nvidia", name="fake", vram_total_mb=8192)

    assert "comfyui" not in enabled_service_keys(TIERS["light"], gpu, {"comfyui"})
    assert "comfyui" not in enabled_service_keys(TIERS["medium"], gpu, {"comfyui"})


def test_enabled_service_keys_heavy_nvidia_includes_comfyui_when_requested():

    gpu = GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)

    assert enabled_service_keys(TIERS["heavy"], gpu, {"comfyui"}) == {
        "ollama", "open-webui", "comfyui"
    }


def test_enabled_service_keys_heavy_amd_includes_comfyui_when_requested():
    """
    AMD has a real, verified ComfyUI image too (corundex/comfyui-rocm,
    targeting RX 6000/7000+ consumer GPUs) - confirmed real and
    published via `docker manifest inspect`, not assumed.
    """

    gpu = GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480)

    assert enabled_service_keys(TIERS["heavy"], gpu, {"comfyui"}) == {
        "ollama", "open-webui", "comfyui"
    }


def test_enabled_service_keys_heavy_intel_includes_comfyui_when_requested():
    """
    Intel Arc has a real, verified ComfyUI image too now
    (yanwk/comfyui-boot:xpu) - confirmed real and published via
    `docker manifest inspect`, not assumed. All three real vendors
    detect.py can detect are covered.
    """

    gpu = GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384)

    assert enabled_service_keys(TIERS["heavy"], gpu, {"comfyui"}) == {
        "ollama", "open-webui", "comfyui"
    }


def test_enabled_service_keys_no_gpu_excludes_comfyui_even_when_requested():
    """
    A real, if currently only theoretical, fallback: comfyui can't
    render without a GPU at all, even though normal recommend_tier()
    flow would never reach Heavy tier with gpu=None in the first place.
    """

    assert enabled_service_keys(TIERS["heavy"], None, {"comfyui"}) == {"ollama", "open-webui"}


def test_enabled_service_keys_heavy_without_requesting_comfyui_omits_it():

    gpu = GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)

    assert enabled_service_keys(TIERS["heavy"], gpu, set()) == {"ollama", "open-webui"}
