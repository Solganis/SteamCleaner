from steamcleaner.ui.gui.app import SteamCleanerGUI


async def main(page):
    gui = SteamCleanerGUI(page)
    await gui.initialize()
