from unittest.mock import patch

from textual.widgets import Button, Checkbox, Input, RadioButton, RadioSet, Static

from installer.detect import GpuInfo, SystemInfo
from installer.tui.app import AnvilApp
from installer.tui.config_screen import ConfigScreen
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
        os_pretty_name="Fedora Linux 44"
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

        await app.workers.wait_for_complete()
        await pilot.pause()

    return app, pilot, ctx


async def _launch_at_config_screen(info: SystemInfo, previous: dict | None = None):

    app, pilot, ctx = await _launch_at_welcome_screen(info, previous)

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


async def test_continue_navigates_to_config_screen():

    app, pilot, ctx = await _launch_at_config_screen(make_system_info())

    try:
        assert isinstance(app.screen, ConfigScreen)
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


async def test_config_screen_back_returns_to_welcome_screen():

    app, pilot, ctx = await _launch_at_config_screen(make_system_info())

    try:

        await pilot.click("#back")
        await pilot.pause()

        assert isinstance(app.screen, WelcomeScreen)

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
            "installer.tui.review_screen.subprocess.run", return_value=MagicMock(returncode=0)
        ) as mock_run:

            await pilot.click("#start")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert app.is_running is False
        mock_run.assert_called_once()

    finally:
        await ctx.__aexit__(None, None, None)
