# Anvil

**A GPU-compute creativity forge.** *(working title — rename freely, nothing depends on it yet)*

Sibling project to [Vulcan](https://github.com/Cyb3rRon1n/vulcan) (a Jellyfin + *arr media stack forge) in the same spirit: inspect a machine's real hardware, recommend a tier it can actually run, generate a ready-to-run Docker Compose stack. Where Vulcan sizes for CPU/RAM/disk, Anvil sizes for **GPU VRAM** — because the workload is different. A local LLM or an image-generation pipeline lives or dies by how much VRAM is actually available, not how many CPU cores the host has.

**Status: real, working build.** Guided TUI by default, plus a scriptable CLI (`--plain`/`--non-interactive`) — detects your GPU's real VRAM (a functional query, not just "is a tool installed"), recommends a tier, generates a Docker Compose stack for Ollama + Open WebUI (+ ComfyUI at Heavy tier on NVIDIA or AMD). Verified against real containers on real hardware where possible; the honest gaps (ComfyUI never run against real NVIDIA/AMD hardware, no Intel Arc ComfyUI image yet) are documented in [CLAUDE.md](CLAUDE.md), not hidden.

## Quick start

```bash
git clone https://github.com/Cyb3rRon1n/anvil.git
cd anvil
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
anvil
```

Detects your CPU/RAM/disk and every GPU with real dedicated VRAM, recommends a tier, asks what you want, and generates `stack/docker-compose.yml` — with the option to start it immediately. A host with no discrete GPU (integrated graphics only) gets a clear explanation and no stack, rather than a tier it can't actually deliver on.

```bash
anvil --plain                           # plain CLI prompts instead of the TUI
anvil --non-interactive --yes --start   # scripted use
```

## Why a separate project, not a Vulcan mode

Scoped out during a Vulcan session that considered and rejected folding "creativity build" services (local LLMs, ComfyUI) into Vulcan directly. These aren't just more services for Vulcan's existing service picker — they need a fundamentally different sizing model (VRAM-bound, not CPU/RAM-bound), a GPU-VRAM detection layer Vulcan's `detect_gpu()` was never built for (vendor presence only, never VRAM amount — and, found while researching this, not even reliably vendor presence: see CLAUDE.md), and a different category of real quirks (model download/storage management, CUDA/ROCm toolkit prerequisites). Full reasoning in [CLAUDE.md](CLAUDE.md).

## What's in the stack

- **Ollama** — local LLM runtime, OpenAI-compatible API. Pulls and manages its own models.
- **Open WebUI** — ChatGPT-style frontend for Ollama. No setup beyond picking a model on first visit.
- **ComfyUI** *(Heavy tier, NVIDIA or AMD)* — node-based image generation. Wires into Open WebUI for inline image generation once both are up — Anvil tells you exactly where to click (Admin Panel > Settings > Images) since that connection is a runtime setting, not something a compose file can do for you. Model checkpoints need to be placed manually; unlike Ollama, ComfyUI doesn't manage its own downloads. No Intel Arc image exists yet — see [CLAUDE.md](CLAUDE.md).

Tiers are based on your GPU's real detected VRAM: **Light** (any real VRAM, small/quantized models), **Medium** (8GB+, comfortable up to ~14B models), **Heavy** (12GB+, adds ComfyUI). See [CLAUDE.md](CLAUDE.md) for where these numbers come from and what's still unverified.

## What's reused from Vulcan vs. genuinely new

See [CLAUDE.md](CLAUDE.md) for the full breakdown — architecture pattern and project discipline carry over, the tier/sizing model and GPU detection do not.
