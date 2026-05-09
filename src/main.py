import flet as ft

from steamcleaner.ui.gui.app import SteamCleanerGUI


async def main(page: ft.Page):
    gui = SteamCleanerGUI(page)
    await gui.initialize()


ft.run(main)
