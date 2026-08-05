"""
Deterministic VRAM-based tier scoring - no LLM in the decision path,
mirroring Vulcan's own "deterministic, not AI-driven" tier principle
even though the workload being sized for happens to be AI. Thresholds
(8GB, 12GB) come from real, commonly-cited community figures researched
for this project (8GB+ VRAM is the widely-repeated threshold for
comfortably running ~14B-class local LLMs and usable image generation;
12GB+ is the frequently-cited "sweet spot," with the RTX 3060 12GB
specifically named as the reference card) - not independently verified
against a real model load yet, see CLAUDE.md's still-open questions.

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
    "light": TierDefinition("light", "Light", min_vram_gb=0.0, services=_LIGHT_SERVICES),
    "medium": TierDefinition("medium", "Medium", min_vram_gb=8.0, services=_MEDIUM_SERVICES),
    "heavy": TierDefinition("heavy", "Heavy", min_vram_gb=12.0, services=_HEAVY_SERVICES),
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
