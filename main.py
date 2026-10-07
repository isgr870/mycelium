import threading
import time
import os
import sys

# Start background Mycelium Bridge engine
def start_backend():
    import mycelium_bridge

backend_thread = threading.Thread(target=start_backend, daemon=True)
backend_thread.start()

# Give local web server 1.5 seconds to bind to 8096
time.sleep(1.5)

# Mobile UI Wrapper using Kivy WebView / Pyjnius
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from jnius import autoclass

WebView = autoclass('android.webkit.WebView')
WebViewClient = autoclass('android.webkit.WebViewClient')
activity = autoclass('org.kivy.android.PythonActivity').mActivity

class MeshApp(App):
    def build(self):
        layout = BoxLayout(orientation='vertical')
        webview = WebView(activity)
        webview.getSettings().setJavaScriptEnabled(True)
        webview.getSettings().setDomStorageEnabled(True)
        webview.getSettings().setAllowFileAccessFromFileURLs(True)
        webview.getSettings().setAllowUniversalAccessFromFileURLs(True)
        webview.setWebViewClient(WebViewClient())
        webview.loadUrl('http://127.0.0.1:8096')
        
        # Add Android WebView to Kivy window
        activity.setContentView(webview)
        return layout

if __name__ == '__main__':
    MeshApp().run()
