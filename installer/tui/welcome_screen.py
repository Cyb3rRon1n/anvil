from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, LoadingIndicator, Static

from installer.detect import SystemInfo, detect_primary_gpu, detect_system
from installer.generate import STACK_DIR, load_previous_state
from installer.tui.docker_screen import DockerReadyScreen


class WelcomeScreen(Screen):

    DEFAULT_CSS = """
    WelcomeScreen {
        align: center middle;
    }

    #results {
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:

        yield Vertical(
            Static("Detecting your system...", id="title"),
            LoadingIndicator(id="loading"),
            Static("", id="results"),
            Static("", id="previous-note"),
            Horizontal(
                Button("Back", id="back"),
                Button("Continue", id="continue", disabled=True),
            ),
        )

    def on_mount(self) -> None:
        self.run_detection()

    @work(thread=True)
    def run_detection(self) -> None:

        info = detect_system()
        previous = load_previous_state(STACK_DIR)

        self.app.call_from_thread(self.detection_complete, info, previous)

    def detection_complete(self, info: SystemInfo, previous: dict | None) -> None:

        self.app.system_info = info
        self.app.previous_state = previous
        self.app.gpu = detect_primary_gpu(info.gpus)

        self.query_one("#loading", LoadingIndicator).display = False

        gpu_lines = (
            "\n".join(
                f"GPU: {g.vendor.upper()}{f' {g.name}' if g.name else ''} - "
                f"{g.vram_total_mb / 1024:.1f}GB VRAM"
                for g in info.gpus
            )
            if info.gpus else "GPU: none with real dedicated VRAM detected"
        )

        self.query_one("#results", Static).update(
            f"CPU: {info.cpu_cores_logical} logical cores ({info.cpu_model or 'unknown'})\n"
            f"RAM: {info.ram_total_gb}GB total\n"
            f"Disk free: {info.disk_free_gb}GB\n"
            f"OS: {info.os_pretty_name or info.os_id or 'unknown'} ({info.architecture})\n"
            f"{gpu_lines}"
        )

        if self.app.gpu is None:

            self.query_one("#previous-note", Static).update(
                "No dedicated GPU with real VRAM detected. Integrated graphics shares "
                "system RAM rather than offering a fixed VRAM pool, which isn't a "
                "credible substitute for local LLM/image-generation workloads - Anvil "
                "has nothing to recommend on this host. Press Ctrl+Q to quit."
            )
            return

        if previous is not None:

            self.query_one("#previous-note", Static).update(
                f"Found an existing {previous['tier']} stack, generated "
                f"{previous['generated_at']}. Using it as defaults."
            )

        self.query_one("#continue", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "continue":
            self.app.push_screen(DockerReadyScreen())
        elif event.button.id == "back":
            self.app.pop_screen()
