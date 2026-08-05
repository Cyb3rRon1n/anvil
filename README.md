# Anvil

**A GPU-compute creativity forge.** *(working title — rename freely, nothing depends on it yet)*

- **What** — Detects your GPU's real VRAM, recommends a sized tier, and generates a ready-to-run Docker Compose stack for local LLMs and image generation.
- **Who it's for** — Homelab and self-hosted folks who want a local AI/creative setup without hand-researching VRAM requirements, Docker images, and GPU passthrough flags per vendor.
- **Why** — Local LLM and image-generation workloads are VRAM-bound, a different sizing problem than [Vulcan](https://github.com/Cyb3rRon1n/vulcan) (a Jellyfin + *arr media stack forge, Anvil's sibling project) solves for CPU/RAM/disk.
- **Where** — Any Linux host with Docker and a real NVIDIA, AMD, or Intel Arc GPU.
- **When to use it** — Real, working build, not a proof of concept. Honest gaps are documented, not hidden — see [CLAUDE.md](CLAUDE.md) for exactly what's verified against real hardware and what isn't yet.

**Status:** Guided TUI by default, plus a scriptable CLI (`--plain`/`--non-interactive`) — detects your GPU's real VRAM (a functional query, not just "is a tool installed"), recommends a tier, generates a Docker Compose stack for Ollama + Open WebUI (+ ComfyUI at Heavy tier — NVIDIA, AMD, and Intel Arc all have a real, verified image). Verified against real containers on real hardware where possible; the honest gap (ComfyUI never run against real discrete GPU hardware of any vendor — none exists in this project's environment) is documented in [CLAUDE.md](CLAUDE.md), not hidden.

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
- **ComfyUI** *(Heavy tier, NVIDIA, AMD, or Intel Arc)* — node-based image generation. Wires into Open WebUI for inline image generation once both are up — Anvil tells you exactly where to click (Admin Panel > Settings > Images) since that connection is a runtime setting, not something a compose file can do for you. Model checkpoints need to be placed manually; unlike Ollama, ComfyUI doesn't manage its own downloads.

Tiers are based on your GPU's real detected VRAM: **Light** (any real VRAM, small quantized models), **Medium** (8GB+, comfortable for 7-9B-class LLMs like Llama 3.1 8B), **Heavy** (12GB+, comfortable for 12-14B-class LLMs like Qwen2.5 14B, plus ComfyUI). Anvil shows you this breakdown for whichever tier you pick, not just its name. See [CLAUDE.md](CLAUDE.md) for the real Ollama/SDXL numbers these are based on.

## What's reused from Vulcan vs. genuinely new

See [CLAUDE.md](CLAUDE.md) for the full breakdown — architecture pattern and project discipline carry over, the tier/sizing model and GPU detection do not.

## License

[MIT](LICENSE)
