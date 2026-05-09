import flet as ft

from steamcleaner.ui.gui.app import SteamCleanerGUI, _WindowHider

hider = _WindowHider()
hider.start()


async def main(page: ft.Page):
    gui = SteamCleanerGUI(page, hider)
    await gui.initialize()


ft.run(main)
