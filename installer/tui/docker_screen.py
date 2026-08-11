import getpass

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, LoadingIndicator, Static

from installer.detect import detect_docker
from installer.docker_setup import (
    add_user_to_docker_group,
    check_docker_ready,
    ensure_compose_v2,
    install_docker,
    install_plan_for,
    start_docker_service,
)
from installer.tui.config_screen import ConfigScreen


class DockerReadyScreen(Screen):
    """
    Ported from Vulcan's own DockerReadyScreen, minus its offline-mode
    branch (Anvil has no --offline concept) and plus one real case
    Vulcan's doesn't have yet: an atomic/immutable host (Bazzite,
    Silverblue, Kinoite - found for real trying Anvil against a real
    GPU host over Tailscale that had no Docker at all). A successful
    rpm-ostree layer needs a reboot before Docker actually exists, so
    that path reports back instead of chaining straight into starting
    the service/adding the group the way every other path does.
    """

    DEFAULT_CSS = """
    DockerReadyScreen {
        align: center middle;
    }

    #docker-status {
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:

        yield Vertical(
            Static("Docker readiness", id="title"),
            Static("", id="docker-status"),
            LoadingIndicator(id="loading"),
            Button("", id="action", disabled=True),
            Horizontal(
                Button("Back", id="back"),
                Button("Continue", id="continue", disabled=True),
            ),
        )

    def on_mount(self) -> None:

        self.query_one("#loading", LoadingIndicator).display = False
        self.render_state()

    def render_state(self) -> None:

        info = self.app.system_info
        action_button = self.query_one("#action", Button)
        continue_button = self.query_one("#continue", Button)
        status = self.query_one("#docker-status", Static)

        if info.docker_installed and info.docker_running and info.docker_compose_v2:

            status.update("Docker is ready.")
            action_button.display = False
            continue_button.disabled = False
            return

        continue_button.disabled = True

        if not info.docker_installed:

            plan = install_plan_for(info.os_id, info.os_is_atomic)

            if plan is None:

                status.update(
                    f"No known automatic install method for '{info.os_id}'. "
                    "Install Docker manually: https://docs.docker.com/engine/install/"
                )
                action_button.display = False
                return

            status.update(f"Docker will be installed via: {plan['description']}")
            action_button.label = "Install Docker"

        elif not info.docker_running:

            status.update("Docker is installed but not running.")
            action_button.label = "Start Docker service"

        elif not info.docker_compose_v2:

            status.update("Docker Compose v2 isn't available.")
            action_button.label = "Install Docker Compose v2"

        action_button.display = True
        action_button.disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "action":

            self.query_one("#action", Button).disabled = True
            self.query_one("#back", Button).disabled = True
            self.query_one("#loading", LoadingIndicator).display = True
            self.run_fix()

        elif event.button.id == "continue":
            self.app.push_screen(ConfigScreen())

        elif event.button.id == "back":
            self.app.pop_screen()

    @work(thread=True)
    def run_fix(self) -> None:

        info = self.app.system_info
        group_just_added = False
        needs_reboot = False

        if not info.docker_installed:

            result = install_docker(info.os_id, info.os_is_atomic)

            if result.get("needs_reboot"):
                needs_reboot = True
            else:
                start_docker_service()
                add_user_to_docker_group(getpass.getuser())
                ensure_compose_v2(info.os_id)
                group_just_added = True

        elif not info.docker_running:

            start_docker_service()

            # Same real gap the CLI's _ensure_docker_ready() fixes -
            # Docker installed by a previous run (the atomic-OS
            # reboot-split case) never got its user added to the
            # docker group, since that only happened alongside a
            # fresh install above. usermod -aG is idempotent.
            add_user_to_docker_group(getpass.getuser())
            group_just_added = True

        elif not info.docker_compose_v2:
            ensure_compose_v2(info.os_id)

        docker_state = detect_docker()

        if group_just_added:

            # A plain detect_docker() re-check here would still see
            # this process's own stale group list - see
            # check_docker_ready()'s docstring for the real failure
            # this fixes (confirmed live against msi-laptop).
            readiness = check_docker_ready(use_group_workaround=True)
            docker_state["docker_running"] = readiness["docker_running"]
            docker_state["docker_compose_v2"] = readiness["docker_compose_v2"]

        self.app.call_from_thread(self.fix_complete, docker_state, group_just_added, needs_reboot)

    def fix_complete(self, docker_state: dict, group_just_added: bool, needs_reboot: bool) -> None:

        self.app.system_info.docker_installed = docker_state["docker_installed"]
        self.app.system_info.docker_running = docker_state["docker_running"]
        self.app.system_info.docker_compose_v2 = docker_state["docker_compose_v2"]

        if group_just_added:
            self.app.group_just_added = True

        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#back", Button).disabled = False

        if needs_reboot:

            self.query_one("#docker-status", Static).update(
                "Docker was layered onto this system via rpm-ostree (atomic/immutable OS "
                "- Bazzite, Silverblue, Kinoite, or similar). This only takes effect after "
                "a reboot - reboot this machine, then relaunch Anvil; it will detect "
                "Docker is installed and pick up from here."
            )
            self.query_one("#action", Button).display = False
            return

        self.render_state()
