from unittest.mock import patch

from textual.widgets import Button, Checkbox, Input, RadioButton, RadioSet, Static

from installer.detect import GpuInfo, SystemInfo
from installer.tui.app import AnvilApp
from installer.tui.config_screen import ConfigScreen
from installer.tui.docker_screen import DockerReadyScreen
from installer.tui.review_screen import ReviewScreen
from installer.tui.welcome_screen import WelcomeScreen


def make_system_info(**overrides) -> SystemInfo:

    base = dict(
        cpu_cores_physical=6,
        cpu_cores_logical=12,
        cpu_model="Test CPU",
        ram_total_gb=32.0,
        disk_free_gb=900.0,
        disk_path_checked="/",
        gpus=[GpuInfo(vendor="nvidia", name="RTX 3060 Ti", vram_total_mb=8192)],
        docker_installed=True,
        docker_running=True,
        docker_compose_v2=True,
        architecture="x86_64",
        os_id="fedora",
        os_pretty_name="Fedora Linux 44",
        os_is_atomic=False
    )

    base.update(overrides)

    return SystemInfo(**base)


async def _launch_at_welcome_screen(info: SystemInfo, previous: dict | None = None):

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=info
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=previous
    ):

        app = AnvilApp()
        ctx = app.run_test()
        pilot = await ctx.__aenter__()

        # MainMenuScreen is the real pushed-on-mount root now (the
        # persistent hub, matching Vulcan's own MainMenuScreen) - push
        # WelcomeScreen explicitly so every screen-flow test below
        # still starts exactly where it did before that change.
        await app.push_screen(WelcomeScreen())
        await app.workers.wait_for_complete()
        await pilot.pause()

    return app, pilot, ctx


async def _launch_at_docker_screen(info: SystemInfo):
    """
    Shared setup landing directly on DockerReadyScreen with a given
    SystemInfo - mirrors Vulcan's own identical helper. AnvilApp's
    on_mount() always pushes WelcomeScreen first, whose own background
    detection worker would otherwise race with - and silently clobber
    - the system_info set here, so WelcomeScreen's real detect_system()
    is mocked and awaited to completion before DockerReadyScreen is
    pushed and the fake info substituted in.
    """

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = AnvilApp()
        ctx = app.run_test()
        pilot = await ctx.__aenter__()

        await app.workers.wait_for_complete()
        await pilot.pause()

    app.system_info = info
    app.gpu = info.gpus[0] if info.gpus else None
    app.push_screen(DockerReadyScreen())
    await pilot.pause()

    return app, pilot, ctx


async def _launch_at_config_screen(info: SystemInfo, previous: dict | None = None):

    app, pilot, ctx = await _launch_at_welcome_screen(info, previous)

    await pilot.click("#continue")
    await pilot.pause()

    # DockerReadyScreen now sits between Welcome and Config - docker
    # is ready by default in make_system_info(), so this just clicks
    # through it the same way a real ready host would.
    await pilot.click("#continue")
    await pilot.pause()

    return app, pilot, ctx


async def test_welcome_screen_no_gpu_disables_continue():

    app, pilot, ctx = await _launch_at_welcome_screen(make_system_info(gpus=[]))

    try:

        assert app.screen.query_one("#continue", Button).disabled is True
        assert "No dedicated GPU" in app.screen.query_one("#previous-note", Static).content

    finally:
        await ctx.__aexit__(None, None, None)


async def test_welcome_screen_with_gpu_enables_continue_and_sets_app_gpu():

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)])
    app, pilot, ctx = await _launch_at_welcome_screen(info)

    try:

        assert app.screen.query_one("#continue", Button).disabled is False
        assert app.gpu == GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_continue_from_welcome_navigates_to_docker_screen():

    app, pilot, ctx = await _launch_at_welcome_screen(make_system_info())

    try:

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, DockerReadyScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_continue_navigates_to_config_screen():

    app, pilot, ctx = await _launch_at_config_screen(make_system_info())

    try:
        assert isinstance(app.screen, ConfigScreen)
    finally:
        await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_already_ready():

    app, pilot, ctx = await _launch_at_docker_screen(make_system_info())

    try:

        status = app.screen.query_one("#docker-status", Static).content
        assert status == "Docker is ready."
        assert app.screen.query_one("#continue", Button).disabled is False
        assert app.screen.query_one("#action", Button).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_not_installed_shows_install_button():

    info = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False
    )

    with patch(
        "installer.tui.docker_screen.install_plan_for",
        return_value={"method": "get.docker.com", "description": "curl ... | sh", "needs_reboot": False}
    ):

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            action = app.screen.query_one("#action", Button)
            assert action.display is True
            assert action.label.plain == "Install Docker"
            assert app.screen.query_one("#continue", Button).disabled is True

        finally:
            await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_unsupported_distro_shows_no_action():

    info = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False,
        os_id="gentoo"
    )

    with patch("installer.tui.docker_screen.install_plan_for", return_value=None):

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            status = app.screen.query_one("#docker-status", Static).content
            assert "No known automatic install method" in status
            assert app.screen.query_one("#action", Button).display is False
            assert app.screen.query_one("#continue", Button).disabled is True

        finally:
            await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_install_button_runs_full_install_sequence():

    info = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False
    )

    ready_state = {
        "docker_installed": True, "docker_running": True, "docker_compose_v2": True
    }

    with patch(
        "installer.tui.docker_screen.install_plan_for",
        return_value={"method": "get.docker.com", "description": "curl ... | sh", "needs_reboot": False}
    ), patch(
        "installer.tui.docker_screen.install_docker",
        return_value={"success": True, "error": None, "method": "get.docker.com", "needs_reboot": False}
    ) as mock_install, patch(
        "installer.tui.docker_screen.start_docker_service"
    ) as mock_start, patch(
        "installer.tui.docker_screen.add_user_to_docker_group"
    ) as mock_add_group, patch(
        "installer.tui.docker_screen.ensure_compose_v2"
    ) as mock_compose, patch(
        "installer.tui.docker_screen.detect_docker",
        return_value={"docker_installed": True, "docker_running": False, "docker_compose_v2": True}
    ), patch(
        "installer.tui.docker_screen.check_docker_ready",
        return_value={"docker_running": True, "docker_compose_v2": True}
    ) as mock_ready:

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            await pilot.click("#action")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            mock_install.assert_called_once()
            mock_start.assert_called_once()
            mock_add_group.assert_called_once()
            mock_compose.assert_called_once()
            mock_ready.assert_called_once_with(use_group_workaround=True)

            assert app.group_just_added is True
            assert app.system_info.docker_installed is True
            assert app.system_info.docker_running is True
            assert app.system_info.docker_compose_v2 is True

            status = app.screen.query_one("#docker-status", Static).content
            assert status == "Docker is ready."
            assert app.screen.query_one("#continue", Button).disabled is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_atomic_host_install_needs_reboot():
    """
    The real case this project's own history didn't cover until a real
    Bazzite GPU host was tried over Tailscale: a successful rpm-ostree
    layer doesn't make Docker usable yet. The screen must report a
    reboot is needed rather than re-rendering as if ready, and must
    not chain into starting the service/adding the group - neither is
    possible before that reboot happens.
    """

    info = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False,
        os_id="bazzite", os_is_atomic=True
    )

    with patch(
        "installer.tui.docker_screen.install_plan_for",
        return_value={
            "method": "rpm-ostree",
            "description": "rpm-ostree install docker-ce ... (needs a reboot)",
            "needs_reboot": True
        }
    ), patch(
        "installer.tui.docker_screen.install_docker",
        return_value={"success": True, "error": None, "method": "rpm-ostree", "needs_reboot": True}
    ), patch(
        "installer.tui.docker_screen.start_docker_service"
    ) as mock_start, patch(
        "installer.tui.docker_screen.add_user_to_docker_group"
    ) as mock_add_group, patch(
        "installer.tui.docker_screen.detect_docker",
        return_value={"docker_installed": False, "docker_running": False, "docker_compose_v2": False}
    ):

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            await pilot.click("#action")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            mock_start.assert_not_called()
            mock_add_group.assert_not_called()
            assert app.group_just_added is False

            status = app.screen.query_one("#docker-status", Static).content
            assert "reboot" in status.lower()
            assert app.screen.query_one("#action", Button).display is False
            assert app.screen.query_one("#continue", Button).disabled is True

        finally:
            await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_not_running_only_starts_service():
    """
    The exact bug found live against msi-laptop: Docker installed by a
    previous run (the atomic-OS reboot-split case) never got its user
    added to the docker group before this fix, since group-adding only
    happened alongside a fresh install. This branch must now also add
    the group and route the re-check through check_docker_ready's
    group-workaround (a plain detect_docker() call right after usermod
    -aG would still see this process's own stale group list).
    """

    info = make_system_info(docker_running=False)

    not_yet_state = {
        "docker_installed": True, "docker_running": False, "docker_compose_v2": True
    }
    ready_state = {"docker_running": True, "docker_compose_v2": True}

    with patch(
        "installer.tui.docker_screen.start_docker_service"
    ) as mock_start, patch(
        "installer.tui.docker_screen.install_docker"
    ) as mock_install, patch(
        "installer.tui.docker_screen.add_user_to_docker_group"
    ) as mock_group, patch(
        "installer.tui.docker_screen.detect_docker", return_value=not_yet_state
    ), patch(
        "installer.tui.docker_screen.check_docker_ready", return_value=ready_state
    ) as mock_ready:

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            action = app.screen.query_one("#action", Button)
            assert action.label.plain == "Start Docker service"

            await pilot.click("#action")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            mock_start.assert_called_once()
            mock_install.assert_not_called()
            mock_group.assert_called_once()
            mock_ready.assert_called_once_with(use_group_workaround=True)
            assert app.group_just_added is True

            status = app.screen.query_one("#docker-status", Static).content
            assert status == "Docker is ready."
            assert app.screen.query_one("#continue", Button).disabled is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_config_screen_defaults_to_recommended_tier():

    # 8GB VRAM -> medium, per tiers.py's real thresholds.
    app, pilot, ctx = await _launch_at_config_screen(make_system_info())

    try:

        radio_set = app.screen.query_one("#tier-set", RadioSet)
        assert radio_set.pressed_button.id == "medium"

    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_tier_radio_buttons_have_real_capability_tooltips():

    from installer.tiers import TIERS

    app, pilot, ctx = await _launch_at_config_screen(make_system_info())

    try:

        for tier_id in ("light", "medium", "heavy"):

            button = app.screen.query_one(f"#{tier_id}", RadioButton)
            assert button.tooltip == TIERS[tier_id].capability_note

    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_comfyui_hidden_at_medium_tier():

    app, pilot, ctx = await _launch_at_config_screen(make_system_info())

    try:
        assert app.screen.query_one("#comfyui-check", Checkbox).display is False
    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_comfyui_visible_at_heavy_tier_nvidia():

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)])
    app, pilot, ctx = await _launch_at_config_screen(info)

    try:
        assert app.screen.query_one("#comfyui-check", Checkbox).display is True
    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_comfyui_visible_at_heavy_tier_amd():

    info = make_system_info(gpus=[GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480)])
    app, pilot, ctx = await _launch_at_config_screen(info)

    try:
        assert app.screen.query_one("#comfyui-check", Checkbox).display is True
    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_comfyui_visible_at_heavy_tier_intel():

    info = make_system_info(gpus=[GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384)])
    app, pilot, ctx = await _launch_at_config_screen(info)

    try:
        assert app.screen.query_one("#comfyui-check", Checkbox).display is True
    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_invokeai_hidden_at_medium_tier():

    app, pilot, ctx = await _launch_at_config_screen(make_system_info())

    try:
        assert app.screen.query_one("#invokeai-check", Checkbox).display is False
    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_invokeai_visible_at_heavy_tier_nvidia():

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)])
    app, pilot, ctx = await _launch_at_config_screen(info)

    try:
        assert app.screen.query_one("#invokeai-check", Checkbox).display is True
    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_invokeai_visible_at_heavy_tier_amd():

    info = make_system_info(gpus=[GpuInfo(vendor="amd", name="RX 7900", vram_total_mb=20480)])
    app, pilot, ctx = await _launch_at_config_screen(info)

    try:
        assert app.screen.query_one("#invokeai-check", Checkbox).display is True
    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_invokeai_hidden_at_heavy_tier_intel():
    """
    Unlike ComfyUI (visible on all three vendors), InvokeAI has no
    official Intel Arc image - the checkbox must stay hidden there.
    """

    info = make_system_info(gpus=[GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384)])
    app, pilot, ctx = await _launch_at_config_screen(info)

    try:
        assert app.screen.query_one("#invokeai-check", Checkbox).display is False
    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_invalid_puid_shows_error_and_does_not_navigate():

    app, pilot, ctx = await _launch_at_config_screen(make_system_info())

    try:

        app.screen.query_one("#puid-input", Input).value = "not-a-number"

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, ConfigScreen)
        assert "must both be numbers" in app.screen.query_one("#config-error", Static).content

    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_continue_stores_tier_and_comfyui_choice():

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)])
    app, pilot, ctx = await _launch_at_config_screen(info)

    try:

        app.screen.query_one("#heavy").value = True
        await pilot.pause()

        app.screen.query_one("#comfyui-check", Checkbox).value = True
        app.screen.query_one("#invokeai-check", Checkbox).value = False

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, ReviewScreen)
        assert app.tier_name == "heavy"
        assert app.enabled_optional == {"comfyui"}

    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_continue_stores_invokeai_choice():

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)])
    app, pilot, ctx = await _launch_at_config_screen(info)

    try:

        app.screen.query_one("#heavy").value = True
        await pilot.pause()

        app.screen.query_one("#comfyui-check", Checkbox).value = False
        app.screen.query_one("#invokeai-check", Checkbox).value = True

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, ReviewScreen)
        assert app.enabled_optional == {"invokeai"}

    finally:
        await ctx.__aexit__(None, None, None)


async def test_config_screen_back_returns_to_docker_screen():
    """
    Genuine pop_screen() semantics, not a hardcoded "go to Welcome" -
    DockerReadyScreen is what's really beneath ConfigScreen on the
    stack now that it sits between Welcome and Config.
    """

    app, pilot, ctx = await _launch_at_config_screen(make_system_info())

    try:

        await pilot.click("#back")
        await pilot.pause()

        assert isinstance(app.screen, DockerReadyScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def _launch_at_review_screen(
    info: SystemInfo, tier_id: str = "medium", enable_comfyui: bool = False, enable_invokeai: bool = False
):

    app, pilot, ctx = await _launch_at_config_screen(info)

    app.screen.query_one(f"#{tier_id}").value = True
    await pilot.pause()

    if tier_id == "heavy":
        # Both checkboxes default on for supported hardware (see
        # config_screen.py) - set explicitly rather than relying on
        # that default, so callers get exactly the combination asked
        # for regardless of which vendors info's GPU supports.
        app.screen.query_one("#comfyui-check", Checkbox).value = enable_comfyui
        app.screen.query_one("#invokeai-check", Checkbox).value = enable_invokeai

    await pilot.click("#continue")
    await pilot.pause()

    return app, pilot, ctx


async def test_review_screen_generate_writes_stack_and_shows_warnings():

    info = make_system_info(gpus=[GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288)])
    app, pilot, ctx = await _launch_at_review_screen(info, tier_id="heavy", enable_comfyui=True)

    try:

        with patch(
            "installer.tui.review_screen.write_stack",
            return_value={
                "success": True,
                "compose_path": "/scratch/stack/docker-compose.yml",
                "warnings": ["fake warning"]
            }
        ) as mock_write_stack:

            await pilot.click("#generate")
            await pilot.pause()

        config = mock_write_stack.call_args[0][0]
        assert config.tier.name == "heavy"
        assert config.enabled_optional == {"comfyui"}

        result_text = app.screen.query_one("#result", Static).content
        assert "Stack written to" in result_text
        assert "fake warning" in result_text
        assert app.screen.query_one("#start", Button).disabled is False
        assert app.screen.query_one("#finish", Button).disabled is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_finish_without_starting_exits_with_command_message():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack",
            return_value={"success": True, "compose_path": "/scratch/stack/docker-compose.yml", "warnings": []}
        ):

            await pilot.click("#generate")
            await pilot.pause()

            await pilot.click("#finish")
            await pilot.pause()

        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_start_success_exits_with_service_urls():

    from unittest.mock import MagicMock

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack",
            return_value={"success": True, "compose_path": "/scratch/stack/docker-compose.yml", "warnings": []}
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.run_docker_command", return_value=MagicMock(returncode=0)
        ) as mock_run:

            await pilot.click("#start")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert app.is_running is False
        mock_run.assert_called_once_with(
            ["docker", "compose", "-f", "/scratch/stack/docker-compose.yml", "up", "-d"],
            use_group_workaround=False
        )

    finally:
        await ctx.__aexit__(None, None, None)
