import threading, time, webbrowser
import uvicorn
import app

def run_server():
    uvicorn.run(app.app, host="127.0.0.1", port=8765, log_level="warning")

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(2.0)
    try:
        import webview
        window = webview.create_window(
            "News Studio AI",
            "http://127.0.0.1:8765",
            width=1500,
            height=960,
            min_size=(1050, 700),
            text_select=True
        )
        webview.start(gui="edgechromium")
    except Exception:
        webbrowser.open("http://127.0.0.1:8765")
        print("News Studio AI is running at http://127.0.0.1:8765")
        print("Close this console to stop the local server.")
        while True:
            time.sleep(60)
