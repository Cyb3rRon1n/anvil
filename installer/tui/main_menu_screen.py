from smithy import HubMenuScreen, MenuItem

from installer.tui.welcome_screen import WelcomeScreen


class MainMenuScreen(HubMenuScreen):
    """
    The persistent hub root, mirroring Vulcan's own MainMenuScreen.
    Anvil's CLI has exactly one real command today (guided setup) - no
    update/backup/restore-equivalents exist yet, so this menu is
    honestly short rather than padded out to look fuller than it is.
    """

    MENU_TITLE = "Anvil"

    def menu_items(self) -> list[MenuItem]:

        return [
            MenuItem(
                id="guided-setup",
                label="Guided Setup",
                tooltip="Detect your GPU, pick a tier, and generate a local AI/creative stack.",
                on_select=lambda screen: screen.app.push_screen(WelcomeScreen()),
            ),
            MenuItem(
                id="exit",
                label="Exit",
                tooltip="Quit Anvil.",
                on_select=lambda screen: screen.app.exit(),
            ),
        ]
