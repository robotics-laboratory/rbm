from webui.hostctl import HostControl
from webui import pages
from nicegui import app, ui
import asyncio


def main():
    hostctl = HostControl()
    app.state.hostctl = hostctl
    app.websocket("/hostctl")(hostctl.ws_handler)

    @app.on_startup
    async def on_startup():
        asyncio.create_task(hostctl.update_loop())

    app.include_router(pages.router)

    ui.run(
        title="ROBOMARVEL",
        show=False,
        port=80,
        reconnect_timeout=10,
        reload=False,
    )


if __name__ == "__main__":
    main()
