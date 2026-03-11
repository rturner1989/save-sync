"""
Entry point: starts the FastAPI server in a background thread and shows a
system-tray icon. Double-click or click "Open" to launch the browser UI.

Requires a system-tray host (KDE, GNOME with AppIndicator extension, etc.).
If pystray fails to load, the server still runs and you can open the UI manually.
"""

import json
import signal
import socket
import sys
import time
import threading
import webbrowser
from pathlib import Path

import uvicorn

CONFIG_PATH = Path.home() / ".config" / "save-sync" / "config.json"


def get_port() -> int:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text()).get("port", 8080)
    return 8080


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def make_icon():
    """Draw a simple coloured circle as the tray icon."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(99, 202, 183))  # teal
    # small inner circle to suggest a sync symbol
    draw.ellipse([20, 20, size - 20, size - 20], fill=(255, 255, 255, 180))
    return img


def wait_for_server(port: int, timeout: float = 10.0) -> bool:
    """Block until the server is accepting connections or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run_server(port: int) -> None:
    from main import app

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def main() -> None:
    port = get_port()
    ip = local_ip()
    url = f"http://{ip}:{port}"

    print(f"Save Sync running at {url}")
    print("Bookmark that address on your iPhone.")

    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()

    # Wait until uvicorn is actually accepting connections before opening browser
    if wait_for_server(port):
        webbrowser.open(f"http://localhost:{port}")
    else:
        print(f"Server did not start in time — open {url} manually")

    try:
        import pystray

        def open_ui(icon, _item):
            webbrowser.open(f"http://localhost:{port}")

        def quit_app(icon, _item):
            icon.stop()
            signal.raise_signal(signal.SIGTERM)

        icon = pystray.Icon(
            "save-sync",
            make_icon(),
            f"Save Sync  ({ip}:{port})",
            menu=pystray.Menu(
                pystray.MenuItem("Open in browser", open_ui, default=True),
                pystray.MenuItem(f"Address: {ip}:{port}", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", quit_app),
            ),
        )
        icon.run()

    except Exception as e:
        print(f"Tray icon unavailable ({e}). Server is still running.")
        print("Press Ctrl-C to stop.")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            print("Stopped.")
            sys.exit(0)


if __name__ == "__main__":
    main()
