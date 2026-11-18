import os, sys, threading, time, webbrowser
import uvicorn
import app
from hardware_profile import apply_low_process_priority

def run_server():
    uvicorn.run(app.app, host="127.0.0.1", port=8765, log_level="warning")

if __name__ == "__main__":
    apply_low_process_priority()
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(2.0)
    if "--server-only" in sys.argv or os.environ.get("NEWS_STUDIO_SERVER_ONLY") == "1":
        print("News Studio AI server is running at http://127.0.0.1:8765/simple")
        while True:
            time.sleep(60)
    try:
        import webview
        window = webview.create_window(
            "News Studio AI",
            "http://127.0.0.1:8765/simple",
            width=1160,
            height=780,
            min_size=(860, 640),
            text_select=True
        )
        webview.start(gui="edgechromium")
    except Exception:
        webbrowser.open("http://127.0.0.1:8765/simple")
        print("News Studio AI is running at http://127.0.0.1:8765/simple")
        print("Close this console to stop the local server.")
        while True:
            time.sleep(60)
