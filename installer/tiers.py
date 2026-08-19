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
    # RAG, voice, and n8n are CPU-only and vendor-agnostic - no
    # vendor_restrictions, and offered at every tier including Light,
    # unlike ComfyUI/InvokeAI which need real GPU compute. Image/env
    # choices sourced from Osmantic/ODS's own real, already-running
    # compose definitions (Apache-2.0) rather than re-researched from
    # scratch - see CLAUDE.md's "RAG + voice + n8n" entry.
    ServiceDefinition("qdrant", "Qdrant (vector database for RAG)", optional=True),
    ServiceDefinition("embeddings", "Text Embeddings Inference (RAG embedding model)", optional=True),
    ServiceDefinition("whisper", "Whisper via speaches (speech-to-text)", optional=True),
    ServiceDefinition("tts", "Kokoro (text-to-speech)", optional=True),
    ServiceDefinition("n8n", "n8n (workflow automation)", optional=True),
    # A second CPU-only, vendor-agnostic slice - LiteLLM/SearXNG real
    # configs sourced from ODS the same way as above; Vane (see below)
    # is not, since ODS's own reference is stale against it. Default
    # off (unlike RAG/voice/n8n) - these are more specialized additions
    # (an LLM proxy needing the user's own API keys, a separate search
    # stack) than direct Open WebUI feature enhancers, and defaulting
    # four more containers on would roughly double a fresh Light install's
    # footprint. A real, decided choice, not an oversight.
    ServiceDefinition("litellm", "LiteLLM (universal LLM proxy - local + cloud providers)", optional=True),
    ServiceDefinition("searxng", "SearXNG (self-hosted metasearch engine)", optional=True),
    # Vane - formerly "Perplexica", renamed upstream. ODS's own
    # reference (image itzcrazykns1337/perplexica:slim-latest, a custom
    # entrypoint wrapper) is stale against the real current project:
    # confirmed via the real upstream repo, which now ships as
    # itzcrazykns1337/vane, no custom entrypoint needed, and configures
    # via a one-time web setup screen instead of a mounted config file -
    # built fresh from that, not ported from ODS. Needs SearXNG to
    # function; write_stack() auto-enables it if requested alone.
    ServiceDefinition("vane", "Vane, formerly Perplexica (AI-powered search - needs SearXNG)", optional=True),
    ServiceDefinition("localai", "LocalAI (OpenAI-compatible multi-modal inference server)", optional=True),
]

_MEDIUM_SERVICES = list(_LIGHT_SERVICES)

_HEAVY_SERVICES = _MEDIUM_SERVICES + [
    ServiceDefinition(
        "comfyui", "ComfyUI (image generation)",
        optional=True, vendor_restrictions=frozenset({"nvidia", "amd", "intel"})
    ),
    ServiceDefinition(
        "invokeai", "InvokeAI (turnkey image generation)",
        optional=True, vendor_restrictions=frozenset({"nvidia", "amd"})
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
            tier=TIERS["light"],
            gpu=None,
            explanation=(
                "No dedicated GPU with real VRAM detected. Ollama still runs on CPU, "
                "and RAG/voice/n8n are CPU-only and vendor-agnostic - Light tier covers "
                "all of it. Integrated graphics shares system RAM rather than offering a "
                "fixed VRAM pool, so it's scored the same as no GPU at all: image "
                "generation (ComfyUI/InvokeAI) and the Medium/Heavy tiers need real "
                "dedicated VRAM and aren't available here."
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
