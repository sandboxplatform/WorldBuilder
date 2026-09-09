#!/usr/bin/env python3
"""
Local server for the editor and viewer.

Serves the project root so sheet images stream straight out of images/extracted --
nothing is copied, and nothing leaves this machine. Adds a small save/load API so
the editor can write maps to maps/ instead of relying on browser downloads.

    python3 tools/serve.py 8823
    editor  -> http://127.0.0.1:8823/editor/
    viewer  -> http://127.0.0.1:8823/viewer/
"""
import functools, http.server, json, os, re, socketserver, sys, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Export shells out to the image tools, which need Pillow. Prefer the project venv
# over whatever interpreter happens to be running the server.
VENV_PY = os.path.join(ROOT, ".venv", "bin", "python")
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable
MAPS = os.path.join(ROOT, "maps")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8823
SAFE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class Handler(http.server.SimpleHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/maps"):
            os.makedirs(MAPS, exist_ok=True)
            names = sorted(f[:-5] for f in os.listdir(MAPS) if f.endswith(".json"))
            return self._json({"maps": names})
        return super().do_GET()

    def _export(self, q):
        """Build a portable bundle: atlas, Tiled JSON, character, manifest."""
        import shutil, subprocess
        name = q.get("name", [""])[0]
        if not SAFE.match(name):
            return self._json({"error": "bad map name"}, 400)
        src = os.path.join(MAPS, f"{name}.json")
        if not os.path.exists(src):
            return self._json({"error": "save the map first"}, 400)
        outdir = os.path.join(ROOT, "out", name)
        os.makedirs(outdir, exist_ok=True)
        r = subprocess.run([PY, os.path.join(ROOT, "tools", "export_atlas.py"),
                            src, outdir, "--name", name, "--profile", "watercooler"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return self._json({"error": r.stderr.strip()[-400:] or "export failed"}, 500)

        manifest = {"map": f"{name}.json", "atlas": f"{name}_atlas.png"}
        char_id = q.get("character", [""])[0]
        if char_id:
            chars = json.load(open(os.path.join(ROOT, "editor", "characters.json")))
            c = next((c for c in chars if c["id"] == char_id), None)
            if c:
                dst = os.path.join(outdir, "character.png")
                shutil.copyfile(os.path.join(ROOT, c["image"]), dst)
                manifest["character"] = {
                    "file": "character.png", "id": c["id"], "frame": c["frame"],
                    "framesPerDir": c["framesPerDir"], "rows": c["rows"],
                    "dirBlocks": c["dirBlocks"],
                }
        m = json.load(open(src))
        # animated placements need their frame layout to travel with the bundle,
        # otherwise the importing project sees a single frozen frame
        ap = os.path.join(ROOT, "editor", "animations.json")
        if os.path.exists(ap):
            anims = json.load(open(ap))
            used = {}
            for L in m.get("layers", []):
                for pl in L.get("placements", []):
                    a = anims.get(pl["id"])
                    if a:
                        used[pl["id"]] = {"frames": a["frames"], "frame": a["frame"],
                                          "tiles": a["tiles"]}
            if used:
                manifest["animations"] = used
        manifest["size"] = m["size"]
        manifest["tile"] = m["tile"]
        manifest["collisions"] = m.get("collisions", [])
        manifest["spawns"] = m.get("spawns", [])
        manifest["note"] = ("Self-contained: the atlas holds every tile this map uses, "
                            "so nothing here depends on the source packs at run time.")
        json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"), indent=1)

        atlas = os.path.join(outdir, f"{name}_atlas.png")
        tiles = 0
        for line in r.stdout.splitlines():
            if "unique tiles" in line:
                tiles = int(line.split("unique tiles")[0].split(",")[-1].strip())
        return self._json({"dir": os.path.relpath(outdir, ROOT), "tiles": tiles,
                           "kb": round(os.path.getsize(atlas) / 1024) if os.path.exists(atlas) else 0,
                           "files": sorted(os.listdir(outdir))})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/export":
            return self._export(q)
        if parsed.path != "/api/save":
            return self._json({"error": "unknown endpoint"}, 404)
        name = urllib.parse.parse_qs(parsed.query).get("name", [""])[0]
        if not SAFE.match(name):
            return self._json({"error": "bad map name"}, 400)
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n))
        except Exception as e:
            return self._json({"error": f"bad payload: {e}"}, 400)
        os.makedirs(MAPS, exist_ok=True)
        path = os.path.join(MAPS, f"{name}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=1)
        return self._json({"saved": os.path.relpath(path, ROOT),
                           "bytes": os.path.getsize(path)})

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        msg = fmt % args
        if "/images/" not in msg:          # sheet images are noisy
            sys.stderr.write(msg + "\n")


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT),
                            functools.partial(Handler, directory=ROOT)) as httpd:
    print(f"WorldBuilder serving {ROOT} on http://127.0.0.1:{PORT}")
    print(f"  editor  http://127.0.0.1:{PORT}/editor/")
    print(f"  viewer  http://127.0.0.1:{PORT}/viewer/")
    httpd.serve_forever()
