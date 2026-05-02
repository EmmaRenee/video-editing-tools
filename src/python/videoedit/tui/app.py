"""
Main TUI application for videoedit.

Provides an interactive terminal interface for building and running
video editing pipelines.
"""
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer

from .screens.home import HomeScreen


class VideoEditApp(App):
    """Main videoedit TUI application."""

    TITLE = "videoedit"
    SUB_TITLE = "AI-first video editing pipeline system"
    CSS_PATH = "styles.css"

    def compose(self) -> ComposeResult:
        """Compose the app."""
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        """Mount the app and show home screen."""
        self.push_screen(HomeScreen())


def main():
    """Run the TUI application."""
    app = VideoEditApp()
    app.run()


if __name__ == "__main__":
    main()
