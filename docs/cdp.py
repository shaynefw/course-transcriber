"""A tiny Chrome DevTools Protocol client (needs the websocket-client package) used to take README screenshots
with a real headless Chrome at any size, including phone sizes at 2x."""
import base64
import json
import subprocess
import time
import urllib.request

import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class Chrome:
    def __init__(self, profile, port=9333):
        self.port = port
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={port}", "--remote-allow-origins=*", f"--user-data-dir={profile}",
             "--hide-scrollbars", "--no-first-run", "--no-default-browser-check", "--disable-extensions", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        tab = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")))
        self.ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=120)
        self.n = 0

    def cmd(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def viewport(self, width, height, dpr=1, mobile=False):
        self.cmd("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=dpr, mobile=mobile)

    def goto(self, url):
        self.cmd("Page.navigate", url=url)
        base = url.split("#")[0]
        for _ in range(150):
            try:
                if self.js("location.href").split("#")[0] == base and self.js("document.readyState") == "complete":
                    return
            except RuntimeError:
                pass
            time.sleep(0.2)

    def js(self, expr):
        """Evaluate JavaScript in the page (async code is awaited). Wrap multi-step code in an async arrow function."""
        r = self.cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", str(r["exceptionDetails"])))
        return r["result"].get("value")

    def shot(self, path):
        data = self.cmd("Page.captureScreenshot", format="png")["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()
