from textual.app import App

from installer.detect import GpuInfo, SystemInfo
from installer.tui.welcome_screen import WelcomeScreen


class AnvilApp(App):
    """
    Session state lives here, not threaded through screen constructors -
    each screen reads/writes these directly via self.app.*, the same
    role GenerationConfig plays by the end of the CLI's own flow.
    Mirrors Vulcan's VulcanApp exactly.
    """

    TITLE = "Anvil"

    def __init__(self) -> None:

        super().__init__()

        self.system_info: SystemInfo | None = None
        self.previous_state: dict | None = None
        self.gpu: GpuInfo | None = None

        self.tier_name: str | None = None
        self.enabled_optional: set[str] = set()
        self.puid: int | None = None
        self.pgid: int | None = None

        # Set True by DockerReadyScreen only when this same session
        # just added the user to the docker group - ReviewScreen's
        # final `docker compose up` needs the sg-based group-refresh
        # workaround in that case (see docker_setup.run_docker_command),
        # since this process's own cached group list is stale.
        self.group_just_added: bool = False

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())
