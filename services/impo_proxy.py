#!/usr/bin/env python3
"""
ImpoReader Proxy v1.0
Запуск: python impo_proxy.py
Затем открывайте imposition-reader.html в браузере
"""
import http.server, urllib.request, urllib.error, json, os, sys

PORT = 5757
OLLAMA_URL = "http://localhost:11434"

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {args[0]} {args[1]}", flush=True)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path == "/ollama":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                req = urllib.request.Request(
                    f"{OLLAMA_URL}/api/generate",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    # Ollama stream — собираем все чанки
                    result_text = ""
                    for line in resp:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            result_text += chunk.get("response", "")
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
                    out = json.dumps({"response": result_text}).encode()
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", len(out))
                    self.end_headers()
                    self.wfile.write(out)
            except urllib.error.URLError as e:
                err = json.dumps({"error": f"Ollama недоступен: {e}"}).encode()
                self.send_response(503)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(err))
                self.end_headers()
                self.wfile.write(err)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        # Отдаём статические файлы (HTML приложение)
        if self.path == "/" or self.path == "":
            self.path = "/imposition-reader.html"
        super().do_GET()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"""
╔══════════════════════════════════════════╗
║       ImpoReader Proxy v1.0              ║
╠══════════════════════════════════════════╣
║  Прокси:  http://localhost:{PORT}          ║
║  Ollama:  {OLLAMA_URL}      ║
╚══════════════════════════════════════════╝

  Откройте в браузере:
  http://localhost:{PORT}

  Для остановки: Ctrl+C
""", flush=True)
    try:
        server = http.server.HTTPServer(("localhost", PORT), ProxyHandler)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлен.")
        sys.exit(0)
    except OSError as e:
        print(f"Ошибка: порт {PORT} занят. Измените PORT в скрипте.")
        sys.exit(1)
