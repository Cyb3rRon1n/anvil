from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, RadioButton, RadioSet, Static

from installer.generate import default_puid_pgid
from installer.tiers import TIERS, recommend_tier
from installer.tui.review_screen import ReviewScreen


class ConfigScreen(Screen):

    DEFAULT_CSS = """
    ConfigScreen {
        align: center middle;
    }

    #config-error {
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:

        recommendation = recommend_tier(self.app.gpu)
        previous = self.app.previous_state

        default_tier = previous["tier"] if previous else recommendation.tier.name

        default_puid, default_pgid = default_puid_pgid()

        if previous:
            default_puid = previous["puid"]
            default_pgid = previous["pgid"]

        gpu = self.app.gpu
        comfyui_supported = gpu is not None and gpu.vendor in ("nvidia", "amd", "intel")

        comfyui_default = (
            "comfyui" in previous["enabled_optional"] if previous else comfyui_supported
        ) and comfyui_supported

        models_path = (
            "stack/data/comfyui/basedir/models" if gpu is not None and gpu.vendor == "nvidia"
            else "stack/data/comfyui/models"
        )

        invokeai_supported = gpu is not None and gpu.vendor in ("nvidia", "amd")

        invokeai_default = (
            "invokeai" in previous["enabled_optional"] if previous else invokeai_supported
        ) and invokeai_supported

        yield Vertical(
            Static(recommendation.explanation, id="recommendation"),
            RadioSet(
                RadioButton(
                    "Light", id="light", value=default_tier == "light",
                    tooltip=TIERS["light"].capability_note
                ),
                RadioButton(
                    "Medium", id="medium", value=default_tier == "medium",
                    tooltip=TIERS["medium"].capability_note
                ),
                RadioButton(
                    "Heavy", id="heavy", value=default_tier == "heavy",
                    tooltip=TIERS["heavy"].capability_note
                ),
                id="tier-set"
            ),
            Checkbox(
                "Enable ComfyUI (image generation)", value=comfyui_default, id="comfyui-check",
                tooltip=(
                    f"Model checkpoints have to be placed manually under {models_path} after "
                    "first start - Ollama pulls its own models automatically, ComfyUI does not."
                )
            ),
            Checkbox(
                "Enable InvokeAI (turnkey image generation)", value=invokeai_default, id="invokeai-check",
                tooltip=(
                    "A simpler alternative to ComfyUI's node-based UI - model checkpoints can be "
                    "downloaded straight from InvokeAI's own built-in Model Manager (HuggingFace "
                    "repo IDs, curated starter models), no manual file placement needed."
                )
            ),
            Input(
                value=str(default_puid), type="integer", placeholder="PUID", id="puid-input",
                tooltip="User ID the containers run as - defaults to your own user."
            ),
            Input(
                value=str(default_pgid), type="integer", placeholder="PGID", id="pgid-input",
                tooltip="Group ID the containers run as - defaults to your own user's group."
            ),
            Static("", id="config-error"),
            Horizontal(
                Button("Back", id="back"),
                Button("Continue", id="continue"),
            ),
        )

    def on_mount(self) -> None:
        self._update_comfyui_visibility(self._current_tier_id())
        self._update_invokeai_visibility(self._current_tier_id())

    def _current_tier_id(self) -> str:
        return self.query_one("#tier-set", RadioSet).pressed_button.id

    def _update_comfyui_visibility(self, tier_id: str) -> None:

        gpu = self.app.gpu
        comfyui_supported = gpu is not None and gpu.vendor in ("nvidia", "amd", "intel")
        self.query_one("#comfyui-check", Checkbox).display = tier_id == "heavy" and comfyui_supported

    def _update_invokeai_visibility(self, tier_id: str) -> None:

        gpu = self.app.gpu
        invokeai_supported = gpu is not None and gpu.vendor in ("nvidia", "amd")
        self.query_one("#invokeai-check", Checkbox).display = tier_id == "heavy" and invokeai_supported

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self._update_comfyui_visibility(event.pressed.id)
        self._update_invokeai_visibility(event.pressed.id)

    def _parse_puid_pgid(self) -> tuple[int, int] | None:

        error = self.query_one("#config-error", Static)

        try:
            puid = int(self.query_one("#puid-input", Input).value)
            pgid = int(self.query_one("#pgid-input", Input).value)
        except ValueError:
            error.update("PUID and PGID must both be numbers.")
            return None

        return puid, pgid

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "back":
            self.app.pop_screen()
            return

        if event.button.id != "continue":
            return

        parsed = self._parse_puid_pgid()

        if parsed is None:
            return

        puid, pgid = parsed
        tier_id = self._current_tier_id()

        enabled_optional = set()

        comfyui_checkbox = self.query_one("#comfyui-check", Checkbox)

        if comfyui_checkbox.display and comfyui_checkbox.value:
            enabled_optional.add("comfyui")

        invokeai_checkbox = self.query_one("#invokeai-check", Checkbox)

        if invokeai_checkbox.display and invokeai_checkbox.value:
            enabled_optional.add("invokeai")

        self.app.tier_name = tier_id
        self.app.puid = puid
        self.app.pgid = pgid
        self.app.enabled_optional = enabled_optional

        self.app.push_screen(ReviewScreen())
