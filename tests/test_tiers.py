from installer.detect import GpuInfo
from installer.tiers import TIERS, enabled_service_keys, recommend_tier


def test_recommend_tier_no_gpu_recommends_light():
    """
    Light tier's own min_vram_gb floor is 0.0 - a GPU-less host isn't
    "nothing to recommend", it's just Light: Ollama runs on CPU, and
    RAG/voice/n8n need no GPU at all. Medium/Heavy and ComfyUI/InvokeAI
    stay correctly unreachable (see enabled_service_keys' own vendor
    gating below), but Light itself must not be blocked.
    """

    result = recommend_tier(None)

    assert result.tier is TIERS["light"]
    assert result.gpu is None
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


def test_enabled_service_keys_light_and_medium_never_include_invokeai():

    gpu = GpuInfo(vendor="nvidia", name="fake", vram_total_mb=8192)

    assert "invokeai" not in enabled_service_keys(TIERS["light"], gpu, {"invokeai"})
    assert "invokeai" not in enabled_service_keys(TIERS["medium"], gpu, {"invokeai"})


def test_enabled_service_keys_heavy_nvidia_includes_invokeai_when_requested():

    gpu = GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)

    assert enabled_service_keys(TIERS["heavy"], gpu, {"invokeai"}) == {
        "ollama", "open-webui", "invokeai"
    }


def test_enabled_service_keys_heavy_amd_includes_invokeai_when_requested():
    """
    InvokeAI's own official docker/ directory ships a real, published
    AMD ROCm image (ghcr.io/invoke-ai/invokeai:main-rocm) - confirmed
    via `docker manifest inspect` and the real docker-compose.yml in
    invoke-ai/InvokeAI, not assumed from a summarized doc fetch.
    """

    gpu = GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480)

    assert enabled_service_keys(TIERS["heavy"], gpu, {"invokeai"}) == {
        "ollama", "open-webui", "invokeai"
    }


def test_enabled_service_keys_heavy_intel_excludes_invokeai_even_when_requested():
    """
    Unlike ComfyUI (which now has a real image for all three detectable
    vendors), InvokeAI has no official Intel Arc image at all - only a
    non-Docker community workaround exists. A real, currently-live gap,
    not a future-vendor hypothetical.
    """

    gpu = GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384)

    assert enabled_service_keys(TIERS["heavy"], gpu, {"invokeai"}) == {"ollama", "open-webui"}


def test_enabled_service_keys_no_gpu_excludes_invokeai_even_when_requested():

    assert enabled_service_keys(TIERS["heavy"], None, {"invokeai"}) == {"ollama", "open-webui"}


def test_enabled_service_keys_heavy_without_requesting_invokeai_omits_it():

    gpu = GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)

    assert enabled_service_keys(TIERS["heavy"], gpu, set()) == {"ollama", "open-webui"}


def test_every_tier_has_a_real_nonempty_capability_note():

    for tier in TIERS.values():
        assert isinstance(tier.capability_note, str)
        assert len(tier.capability_note) > 0


def test_medium_capability_note_no_longer_claims_comfortable_14b():
    """
    Regression lock for the corrected claim: real Ollama Q4_K_M sizes
    (Qwen2.5 14B = 9.0GB) show a 14B model doesn't leave real context
    headroom on an 8GB card - that comfort level belongs at Heavy
    (12GB), not Medium. See tiers.py's module docstring/CLAUDE.md for
    the full math.
    """

    assert "Comfortable for 14B" not in TIERS["medium"].capability_note
    assert "little room to spare" in TIERS["medium"].capability_note


def test_heavy_capability_note_claims_14b_comfort():
    assert "14B" in TIERS["heavy"].capability_note


# --- RAG/voice/n8n: CPU-only, vendor-agnostic, offered at every tier ---


def test_rag_voice_n8n_available_at_light_tier_with_no_gpu():
    """
    Unlike ComfyUI/InvokeAI, RAG/voice/n8n need no GPU at all - must be
    requestable with gpu=None, which recommend_tier() itself now also
    reaches Light through (see test_recommend_tier_no_gpu_recommends_
    light above); enabled_service_keys() is exercised directly here too.
    """

    requested = {"qdrant", "embeddings", "whisper", "tts", "n8n"}

    assert enabled_service_keys(TIERS["light"], None, requested) == {
        "ollama", "open-webui", "qdrant", "embeddings", "whisper", "tts", "n8n"
    }


def test_rag_voice_n8n_available_at_every_tier_regardless_of_gpu_vendor():

    requested = {"qdrant", "embeddings", "whisper", "tts", "n8n"}

    for tier_name in ("light", "medium", "heavy"):
        for gpu in (
            None,
            GpuInfo(vendor="nvidia", name="fake", vram_total_mb=12288),
            GpuInfo(vendor="amd", name="fake", vram_total_mb=12288),
            GpuInfo(vendor="intel", name="fake", vram_total_mb=12288),
        ):
            enabled = enabled_service_keys(TIERS[tier_name], gpu, requested)
            assert requested <= enabled


def test_litellm_searxng_vane_localai_available_at_every_tier_regardless_of_gpu_vendor():

    requested = {"litellm", "searxng", "vane", "localai"}

    for tier_name in ("light", "medium", "heavy"):
        for gpu in (None, GpuInfo(vendor="nvidia", name="fake", vram_total_mb=12288)):
            enabled = enabled_service_keys(TIERS[tier_name], gpu, requested)
            assert requested <= enabled


def test_rag_voice_n8n_omitted_when_not_requested():

    gpu = GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)

    assert enabled_service_keys(TIERS["heavy"], gpu, set()) == {"ollama", "open-webui"}
