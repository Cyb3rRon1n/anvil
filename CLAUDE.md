# CLAUDE.md

Design notes for Anvil, written at concept stage so the reasoning survives between sessions. **Nothing in this document is verified against real hardware or real services** — it's a scope-preserving sketch, not a design ready for implementation. Treat every specific (image name, port, VRAM figure) as a placeholder to re-verify for real when work actually starts, the same discipline Vulcan holds itself to for everything it claims.

## Origin

Scoped out during a Vulcan session where the user asked whether Vulcan should grow "build type" selection (Media Server vs. Creativity) to cover local LLMs, ComfyUI, and Stable Diffusion alongside Jellyfin/*arr. The recommendation was to keep Vulcan narrow and spin this out as its own project instead — captured here so the idea isn't lost, not because the idea was bad.

## Why this can't just be a Vulcan mode

- **Different sizing axis entirely.** Vulcan's `TierDefinition` scores on CPU cores, RAM, and disk — right for a media stack, meaningless for GPU-compute workloads. A 7B-parameter LLM needs roughly 8GB of VRAM; a 70B needs 40GB+; none of that has anything to do with system RAM or CPU core count. Anvil's tiers would need to score primarily on **GPU VRAM** (and probably vendor/compute-capability), a dimension Vulcan's tier model has no hook for at all.
- **Vulcan's GPU detection was never built for this.** `detect_gpu()` (Vulcan's `installer/detect.py`) only checks vendor presence via `nvidia-smi`/`rocm-smi`/an `lspci` string match — confirmed by reading it, not assumed. It has never needed to know *how much* VRAM exists, because Jellyfin's hardware transcoding doesn't care. Anvil's whole tier model depends on that number.
- **A different category of real quirks.** Vulcan's "one hand-written compose block per service, because each carries small real quirks" convention exists because that's genuinely cheaper than a generic renderer for 17 services with real per-service gotchas. Anvil's services would carry a different set of real gotchas — model download/storage management (Ollama pulls models via its own mechanism; ComfyUI/A1111 typically expect models placed manually), CUDA/ROCm toolkit prerequisites (Vulcan already documents `nvidia-container-toolkit` as a real, currently-unsolved gap for its own *optional* NVIDIA transcoding path — for Anvil, GPU compute isn't optional, it's the entire point, so this gap can't be left unsolved the way Vulcan leaves it). That's a second full set of real-infrastructure verification work, not an extension of Vulcan's existing set.
- **Different storage assumptions.** Model files run 4GB–140GB+ each. Vulcan's hardlink-safe `${MEDIA_PATH}:/data` volume convention (built around a media library's directory shape: movies/tv/music/books) doesn't map cleanly onto "where do multi-gigabyte model weights live and how do multiple services share them without duplicating downloads."

## What genuinely carries over from Vulcan's architecture

Not the tier model or GPU detection — the *pattern* around them, which is domain-agnostic and already proven:

- **Detect → recommend → generate**, the same three-stage shape Vulcan's `detect.py` → `tiers.py` → `generate.py` already establish.
- **Pure manager functions, never raising** — every real operation returns a plain result dict (`{"success"/"available": bool, "error": str | None, ...}`), the CLI/TUI layer alone owns confirmation prompts and stdout/stderr. Vulcan's engine/front-end split (`installer/` engine modules stay prompt-free; `cli.py`/`tui/` own all interaction) is worth copying exactly.
- **Two front ends over one engine** — a Typer CLI plus a Textual TUI, neither owning logic the other lacks. Vulcan's `installer/cli.py` + `installer/tui/` is a proven, reusable shape for this.
- **Docker Compose generation via Jinja, one block per known service** — not a generic data-driven renderer. Vulcan's own documented reasoning for this (real per-service quirks are easier to read and maintain as literal, mostly-static template blocks) likely holds here too, once the real service list and their real quirks are known.
- **Real-infrastructure verification as a non-negotiable project value, not optional polish.** Every Vulcan feature in this workspace ships with a "verified against a real container/real hardware" step, and claims are written to reflect exactly what was and wasn't checked. Anvil should hold itself to the identical bar — a `nvidia-smi`-based VRAM check that's never been run against a real GPU is exactly the kind of unverified claim Vulcan's own CLAUDE.md is careful never to make.
- **No LLM in the sizing decision path**, ironic as that sounds for a project that deploys LLMs — Vulcan's "deterministic, not AI-driven" tier scoring is a real design principle (reproducible, explainable, no hidden model behavior in *how a recommendation gets made*), and there's no reason Anvil's own tier math shouldn't be equally deterministic even though the workload it's sizing for happens to be AI.

## Real open questions for whenever this starts for real

None of these have been researched yet — listed so they're not forgotten, not because they're answered:

- **VRAM detection mechanism.** `nvidia-smi --query-gpu=memory.total` is the obvious NVIDIA candidate; the real equivalent for AMD (ROCm's `rocm-smi`) and Intel Arc needs actual research, not assumption. Multi-GPU hosts add a real question (sum VRAM? size for the largest single card? let the user choose which GPU?).
- **Real VRAM requirements per candidate service/model size** — the 7B/70B figures above are commonly-cited rules of thumb, not something this project has verified against a real model load.
- **CUDA/ROCm toolkit installation** — Vulcan defers this entirely (documents it as a gap, doesn't solve it). Anvil likely can't defer it the same way, since GPU compute is the core function here, not an optional add-on.
- **Model storage strategy** — shared model directory across services vs. per-service, and whether/how to avoid the same model being downloaded twice for two different tools that both want it.
- **Real candidate image tags, ports, and first-run quirks** for every service in the README's candidate list — none of this has had Vulcan's own level of scrutiny (real `docker manifest inspect`, real container start, real log inspection) yet.
- **Naming.** "Anvil" is a working title picked for the Vulcan-forge/anvil pairing, not a final decision.
