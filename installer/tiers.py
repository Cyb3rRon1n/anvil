"""
Deterministic VRAM-based tier scoring - no LLM in the decision path,
mirroring Vulcan's own "deterministic, not AI-driven" tier principle
even though the workload being sized for happens to be AI. Thresholds
(8GB, 12GB) started as real, commonly-cited community figures - since
verified against real, hard numbers instead: Ollama's own published
Q4_K_M download sizes (Llama 3.1 8B = 4.9GB, Qwen2.5 14B = 9.0GB) and
cross-referenced SDXL/ComfyUI VRAM guidance (12GB repeatedly cited as
the real sweet spot for a refiner pipeline). See CLAUDE.md's "model
capability verification" entry for the full source list and math.

That verification corrected one thing: the original claim that 8GB is
"comfortable up to ~14B models" was optimistic - a 14B model's weights
alone already consume 9GB at Q4_K_M, leaving little headroom for
context on an 8GB card. 14B-class comfort genuinely belongs at the
12GB Heavy tier, not Medium; each tier's `capability_note` below
reflects the corrected claim, not the original one - the two 8/12GB
threshold numbers themselves held up fine and didn't need to move.

A host with no real dedicated VRAM (integrated-only graphics, or no
GPU at all) gets no tier at all - a deliberate scoping decision, not
a gap: Unified Memory Architecture iGPUs share system RAM rather than
offering a fixed VRAM pool, and that's not a credible substitute for
what a 7B+ model actually needs. See detect.py/CLAUDE.md.
"""

from dataclasses import dataclass

from installer.detect import GpuInfo


@dataclass
class ServiceDefinition:

    key: str
    display_name: str
    optional: bool = False
    vendor_restrictions: frozenset[str] | None = None  # e.g. {"nvidia", "amd"} - None means vendor-agnostic


@dataclass
class TierDefinition:

    name: str
    display_name: str
    min_vram_gb: float
    services: list[ServiceDefinition]
    capability_note: str


_LIGHT_SERVICES = [
    ServiceDefinition("ollama", "Ollama (local LLM runtime)"),
    ServiceDefinition("open-webui", "Open WebUI (chat interface)"),
]

_MEDIUM_SERVICES = list(_LIGHT_SERVICES)

_HEAVY_SERVICES = _MEDIUM_SERVICES + [
    ServiceDefinition(
        "comfyui", "ComfyUI (image generation)",
        optional=True, vendor_restrictions=frozenset({"nvidia", "amd", "intel"})
    ),
]

TIERS: dict[str, TierDefinition] = {
    "light": TierDefinition(
        "light", "Light", min_vram_gb=0.0, services=_LIGHT_SERVICES,
        capability_note=(
            "Small quantized models only (roughly 1-3B at Q4); a 7B model "
            "(~5GB at Q4_K_M) may fit on the higher end of this range but with little "
            "headroom for context."
        )
    ),
    "medium": TierDefinition(
        "medium", "Medium", min_vram_gb=8.0, services=_MEDIUM_SERVICES,
        capability_note=(
            "Comfortable for 7-9B-class models (e.g. Llama 3.1 8B, ~4.9GB at Q4_K_M) "
            "with real headroom for context. 12-14B models fit VRAM-wise but leave "
            "little room to spare - see Heavy."
        )
    ),
    "heavy": TierDefinition(
        "heavy", "Heavy", min_vram_gb=12.0, services=_HEAVY_SERVICES,
        capability_note=(
            "Comfortable for 12-14B-class models (e.g. Qwen2.5 14B, ~9GB at Q4_K_M) "
            "with real context headroom, and the commonly-cited sweet spot for SDXL "
            "image generation via ComfyUI."
        )
    ),
}

ALL_SERVICES: list[ServiceDefinition] = _HEAVY_SERVICES

_ORDERED_HIGH_TO_LOW = ["heavy", "medium", "light"]


@dataclass
class Recommendation:

    tier: TierDefinition | None
    gpu: GpuInfo | None
    explanation: str


def recommend_tier(gpu: GpuInfo | None) -> Recommendation:

    if gpu is None:

        return Recommendation(
            tier=None,
            gpu=None,
            explanation=(
                "No dedicated GPU with real VRAM detected. Integrated graphics shares "
                "system RAM rather than offering a fixed VRAM pool, which isn't a "
                "credible substitute for what local LLM/image-generation workloads need - "
                "Anvil has nothing to recommend on this host."
            )
        )

    vram_gb = gpu.vram_total_mb / 1024

    for name in _ORDERED_HIGH_TO_LOW:

        tier = TIERS[name]

        if vram_gb >= tier.min_vram_gb:

            return Recommendation(
                tier=tier,
                gpu=gpu,
                explanation=(
                    f"{gpu.vendor.upper()} GPU with {vram_gb:.1f}GB VRAM "
                    f"{f'({gpu.name}) ' if gpu.name else ''}qualifies for {tier.display_name}."
                )
            )

    # Unreachable given light's 0.0 floor, kept for exhaustiveness.
    return Recommendation(tier=TIERS["light"], gpu=gpu, explanation="Below every real threshold.")


def enabled_service_keys(tier: TierDefinition, gpu: GpuInfo | None, enabled_optional: set[str]) -> set[str]:

    keys = set()

    for service in tier.services:

        if service.optional and service.key not in enabled_optional:
            continue

        if service.vendor_restrictions and (gpu is None or gpu.vendor not in service.vendor_restrictions):
            continue

        keys.add(service.key)

    return keys
