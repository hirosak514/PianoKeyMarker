#!/usr/bin/env python3
# 楽譜読み取りソフト Webアプリ版 の簡易サーバー。
# このファイルをダブルクリックする（または start_server.bat をダブルクリックする）と、
# サーバーが起動し、自動でブラウザが開きます。終了するときは黒いウィンドウを閉じてください。
#
# 「python -m http.server」ではなくこれを使う理由:
#   Windows では .mjs / .wasm ファイルの種類(MIMEタイプ)が正しく判定されず、
#   ブラウザ内解析の部品が読み込めないことがあるため、ここで正しい種類を明示している。

import http.server
import os
import socketserver
import sys
import threading
import webbrowser

PORT = 8000

EXTRA_TYPES = {
    ".mjs": "text/javascript",
    ".js": "text/javascript",
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".onnx": "application/octet-stream",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        lower = str(path).lower()
        for ext, ctype in EXTRA_TYPES.items():
            if lower.endswith(ext):
                return ctype
        return super().guess_type(path)

    def end_headers(self):
        # 古いキャッシュ（誤った種類で保存されたもの）を使わせない
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # アクセスログは表示しない（画面をすっきりさせる）


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    # ダブルクリックで起動しても、このファイルがあるフォルダを配信する
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    port = PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    url = f"http://localhost:{port}/index.html"
    try:
        httpd = Server(("127.0.0.1", port), Handler)
    except OSError:
        # すでに起動済み（ポート使用中）の場合は、ブラウザだけ開く
        print("サーバーはすでに起動しているようです。ブラウザを開きます。")
        webbrowser.open(url)
        input("Enterキーでこのウィンドウを閉じます...")
        return

    print("==============================================")
    print(" 楽譜読み取りソフト Webアプリ版")
    print("==============================================")
    print(f"起動しました: {url}")
    print("ブラウザが開かない場合は、上のアドレスを手動で開いてください。")
    print("終了するときは、このウィンドウを閉じてください。")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
