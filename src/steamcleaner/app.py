from steamcleaner.ui.gui.app import run_gui
from steamcleaner.utils.logging import setup_logging


def main():
    setup_logging()
    run_gui()
