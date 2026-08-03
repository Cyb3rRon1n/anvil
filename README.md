# Anvil

**A GPU-compute creativity forge.** *(working title — rename freely, nothing depends on it yet)*

Sibling project to [Vulcan](https://github.com/Cyb3rRon1n/vulcan) (a Jellyfin + *arr media stack forge) in the same spirit: inspect a machine's real hardware, recommend a tier it can actually run, generate a ready-to-run Docker Compose stack. Where Vulcan sizes for CPU/RAM/disk, Anvil sizes for **GPU VRAM** — because the workload is different. A local LLM, an image-generation pipeline, or a video-generation model lives or dies by how much VRAM is actually available, not how many CPU cores the host has.

**Status: concept stage.** Nothing in this repo has been built, run, or verified against real hardware yet. This is a scope-preserving sketch, written up so the idea and its reasoning survive between sessions — see [CLAUDE.md](CLAUDE.md) for the design notes and everything still genuinely unknown.

## Why a separate project, not a Vulcan mode

Scoped out during a Vulcan session that considered and rejected folding "creativity build" services (local LLMs, ComfyUI, Stable Diffusion) into Vulcan directly. The reasoning, in short: these aren't just more services for Vulcan's existing service picker — they need a fundamentally different sizing model (VRAM-bound, not CPU/RAM-bound), a GPU-VRAM detection layer Vulcan's `detect_gpu()` was never built for (vendor presence only, never VRAM amount), and a different category of real quirks (model download/storage management, CUDA/ROCm toolkit prerequisites) with the same hand-verified rigor Vulcan already holds itself to for its own 17 services. Doing it well means a second tier model built around VRAM from day one, not one bolted onto Vulcan's CPU/RAM-centric tiers. Full reasoning in [CLAUDE.md](CLAUDE.md).

## Candidate services (unverified, starting point only)

Not yet researched with Vulcan's own rigor (real image tags, real VRAM requirements, real first-run quirks) — just a plausible starting list to scope against later:

- **Ollama** — local LLM serving. Real image confirmed to exist (`ollama/ollama`, multi-arch) — nothing else about it verified yet.
- **Open WebUI** — chat frontend for Ollama.
- **ComfyUI** — node-based image/video generation.
- **Stable Diffusion WebUI (AUTOMATIC1111)** — more turnkey alternative to ComfyUI.

## What's reused from Vulcan vs. genuinely new

See [CLAUDE.md](CLAUDE.md) for the full breakdown — architecture pattern and project discipline carry over, the tier/sizing model and GPU detection do not.
