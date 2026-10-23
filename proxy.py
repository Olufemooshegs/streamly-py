# proxy.py
import http.server
import urllib.request
import urllib.error

PORT = 8001
TARGET = "http://127.0.0.1:8000"

class BufferingProxy(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        req = urllib.request.Request(TARGET + self.path)
        try:
            with urllib.request.urlopen(req) as response:
                self.send_response(response.status)
                for k, v in response.getheaders():
                    self.send_header(k, v)
                self.end_headers()
                
                # If it's normal files, pass them through
                if "/events" not in self.path:
                    data = response.read()
                    self.wfile.write(data)
                    return
                
                # THE BUG: Buffer the SSE stream and starve the client
                print(f"⚠️ Proxy intercepted SSE stream at {self.path}. Buffering silently...")
                while True:
                    chunk = response.read(1024)
                    if not chunk:
                        break
                    pass 
                
        except Exception as e:
            self.send_error(502, str(e))

    def do_POST(self):
        # Forward POST requests to the backend without buffering
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        req = urllib.request.Request(TARGET + self.path, data=post_data, method="POST")
        for k, v in self.headers.items():
            if k.lower() not in ['host', 'content-length']:
                req.add_header(k, v)
                
        try:
            with urllib.request.urlopen(req) as response:
                self.send_response(response.status)
                for k, v in response.getheaders():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(response.read())
        except urllib.error.HTTPError as e:
            self.send_error(e.code, e.reason)
        except Exception as e:
            self.send_error(502, str(e))

if __name__ == "__main__":
    print(f"⚠️ Buffering Proxy running on http://127.0.0.1:{PORT}")
    http.server.HTTPServer(("", PORT), BufferingProxy).serve_forever()