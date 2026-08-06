import subprocess

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, LoadingIndicator, Static

from installer.generate import GenerationConfig, write_stack
from installer.tiers import TIERS


class ReviewScreen(Screen):

    DEFAULT_CSS = """
    ReviewScreen {
        align: center middle;
    }

    #result {
        margin: 1 0;
    }
    """

    def _build_config(self) -> GenerationConfig:

        return GenerationConfig(
            tier=TIERS[self.app.tier_name],
            puid=self.app.puid,
            pgid=self.app.pgid,
            gpu=self.app.gpu,
            enabled_optional=self.app.enabled_optional
        )

    def compose(self) -> ComposeResult:

        tier = TIERS[self.app.tier_name]
        gpu = self.app.gpu

        summary = (
            f"Tier: {tier.display_name}\n"
            f"  {tier.capability_note}\n"
            f"GPU: {gpu.vendor.upper() if gpu else 'none'}\n"
            f"PUID/PGID: {self.app.puid}/{self.app.pgid}\n"
            f"ComfyUI: {'enabled' if 'comfyui' in self.app.enabled_optional else 'disabled'}\n"
            f"InvokeAI: {'enabled' if 'invokeai' in self.app.enabled_optional else 'disabled'}"
        )

        yield Vertical(
            Static(summary, id="summary"),
            Horizontal(
                Button("Back", id="back"),
                Button("Generate", id="generate"),
            ),
            Static("", id="result"),
            LoadingIndicator(id="loading"),
            Horizontal(
                Button("Start Stack Now", id="start", disabled=True),
                Button("Finish Without Starting", id="finish", disabled=True),
            ),
        )

    def on_mount(self) -> None:

        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#start", Button).display = False
        self.query_one("#finish", Button).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "generate":
            self._generate()
        elif event.button.id == "finish":
            self._finish_without_starting()
        elif event.button.id == "start":
            self._start_stack()

    def _generate(self) -> None:

        self.query_one("#generate", Button).disabled = True
        result_widget = self.query_one("#result", Static)

        self._config = self._build_config()
        result = write_stack(self._config)

        self._compose_path = result["compose_path"]

        lines = [f"Stack written to {result['compose_path']}"]
        lines.extend(f"! {warning}" for warning in result["warnings"])
        result_widget.update("\n".join(lines))

        for button_id in ("start", "finish"):

            button = self.query_one(f"#{button_id}", Button)
            button.display = True
            button.disabled = False

    def _finish_without_starting(self) -> None:

        self.app.exit(
            message=f"Run this when you're ready:\n  docker compose -f {self._compose_path} up -d"
        )

    def _start_stack(self) -> None:

        self.query_one("#start", Button).disabled = True
        self.query_one("#finish", Button).disabled = True
        self.query_one("#back", Button).disabled = True
        self.query_one("#loading", LoadingIndicator).display = True

        self._run_start()

    @work(thread=True)
    def _run_start(self) -> None:

        proc = subprocess.run(["docker", "compose", "-f", self._compose_path, "up", "-d"])

        self.app.call_from_thread(self._start_complete, proc.returncode)

    def _start_complete(self, returncode: int) -> None:

        if returncode == 0:

            message = (
                "Stack is up:\n"
                "  Dashboard:    http://localhost:8080\n"
                "  Ollama API:   http://localhost:11434\n"
                "  Open WebUI:   http://localhost:3000"
            )

            if "comfyui" in self._config.enabled_optional:
                message += "\n  ComfyUI:      http://localhost:8188"

            if "invokeai" in self._config.enabled_optional:
                message += "\n  InvokeAI:     http://localhost:9090"

            self.app.exit(message=message)

        else:
            self.app.exit(message="Failed to start the stack - check `docker compose logs`.")
