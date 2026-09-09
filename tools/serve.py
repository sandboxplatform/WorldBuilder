#!/usr/bin/env python3
"""
Server for the editor and viewer -- the same program locally and deployed.

Locally it binds 127.0.0.1 and serves the project root, so sheet images stream
straight out of images/extracted: nothing is copied and nothing leaves the machine.

Deployed it reads its configuration from the environment:

    PORT        bind port, and binding moves to 0.0.0.0 (Railway sets this)
    WB_USER     enable HTTP basic auth -- without both of these there is no login,
    WB_PASS       which is right for localhost and wrong for anything public
    WB_MAPS     where maps are saved       (default <root>/maps)
    WB_OUT      where export bundles land  (default <root>/out)

    python3 tools/serve.py 8823
    editor  -> http://127.0.0.1:8823/editor/
    viewer  -> http://127.0.0.1:8823/viewer/
"""
import base64, functools, hmac, http.server, io, json, os, re, sys, urllib.parse, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Export shells out to the image tools, which need Pillow. Prefer the project venv
# over whatever interpreter happens to be running the server.
VENV_PY = os.path.join(ROOT, ".venv", "bin", "python")
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable

MAPS = os.environ.get("WB_MAPS") or os.path.join(ROOT, "maps")
OUT = os.environ.get("WB_OUT") or os.path.join(ROOT, "out")
USER, PASS = os.environ.get("WB_USER"), os.environ.get("WB_PASS")

# $PORT is how a platform tells us to listen; its presence means we are not local.
ENV_PORT = os.environ.get("PORT")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(ENV_PORT or 8823)
HOST = "0.0.0.0" if ENV_PORT else "127.0.0.1"

SAFE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
# Sheet art never changes: cache it for a year so a session downloads each sheet once
# rather than on every click. The indexes are rebuilt by the tools, so they revalidate.
IMMUTABLE = re.compile(r"^/(images|web_assets)/|^/editor/thumbs_.*\.png$")


class Handler(http.server.SimpleHTTPRequestHandler):
    # ------------------------------------------------------------------ helpers
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self):
        """Basic auth, on only when both credentials are configured."""
        if not (USER and PASS):
            return True
        got = self.headers.get("Authorization", "")
        if got.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(got[6:]).decode().partition(":")
            except Exception:
                user = pw = ""
            # compare_digest on both halves: a plain == leaks length by timing
            if hmac.compare_digest(user, USER) and hmac.compare_digest(pw, PASS):
                return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="WorldBuilder"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _forbidden(self):
        """Nothing outside the app: no .git, no .venv, no dotfiles."""
        path = urllib.parse.urlparse(self.path).path
        return any(seg.startswith(".") for seg in path.split("/") if seg)

    # ------------------------------------------------------------------ routes
    def do_GET(self):
        if not self._authorised():
            return
        if self._forbidden():
            return self._json({"error": "not found"}, 404)
        parsed = urllib.parse.urlparse(self.path)
        # The root is the app. Locally you learn to type /editor/; deployed, the bare
        # URL is what you hand someone, and it used to answer with a file listing.
        if parsed.path == "/":
            self.send_response(302)
            self.send_header("Location", "/editor/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if parsed.path == "/api/maps":
            os.makedirs(MAPS, exist_ok=True)
            names = sorted(f[:-5] for f in os.listdir(MAPS) if f.endswith(".json"))
            return self._json({"maps": names})
        if parsed.path == "/api/map":
            return self._read_map(urllib.parse.parse_qs(parsed.query))
        if parsed.path == "/api/download":
            return self._download(urllib.parse.parse_qs(parsed.query))
        return super().do_GET()

    def do_HEAD(self):
        if not self._authorised():
            return
        return super().do_HEAD()

    def do_POST(self):
        if not self._authorised():
            return
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/export":
            return self._export(q)
        if parsed.path == "/api/save":
            return self._save(q)
        if parsed.path == "/api/delete":
            return self._delete(q)
        return self._json({"error": "unknown endpoint"}, 404)

    def _read_map(self, q):
        name = q.get("name", [""])[0]
        if not SAFE.match(name):
            return self._json({"error": "bad map name"}, 400)
        path = os.path.join(MAPS, f"{name}.json")
        if not os.path.exists(path):
            return self._json({"error": "no such map"}, 404)
        return self._json(json.load(open(path)))

    def _save(self, q):
        name = q.get("name", [""])[0]
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
        return self._json({"saved": os.path.basename(path),
                           "bytes": os.path.getsize(path)})

    def _delete(self, q):
        """Remove a saved map, and the export bundle built from it -- leaving that
        behind would keep a stale zip downloadable for a world that no longer exists."""
        import shutil
        name = q.get("name", [""])[0]
        if not SAFE.match(name):
            return self._json({"error": "bad map name"}, 400)
        path = os.path.join(MAPS, f"{name}.json")
        if not os.path.exists(path):
            return self._json({"error": "no such map"}, 404)
        os.remove(path)
        bundle = os.path.join(OUT, name)
        had_bundle = os.path.isdir(bundle)
        if had_bundle:
            shutil.rmtree(bundle)
        return self._json({"deleted": name, "bundle": had_bundle})

    def _export(self, q):
        """Build a portable bundle: atlas, Tiled JSON, character, manifest."""
        import shutil, subprocess
        name = q.get("name", [""])[0]
        if not SAFE.match(name):
            return self._json({"error": "bad map name"}, 400)
        src = os.path.join(MAPS, f"{name}.json")
        if not os.path.exists(src):
            return self._json({"error": "save the map first"}, 400)
        # An empty map packs a zero-tile atlas, which Pillow refuses to save with a
        # traceback -- and "export bundle" is a plausible first click on a blank map.
        m = json.load(open(src))
        used = any(any(row) for L in m.get("layers", []) for row in L.get("grid") or []) \
            or any(L.get("placements") for L in m.get("layers", []))
        if not used:
            return self._json({"error": "nothing to export — paint something first"}, 400)

        outdir = os.path.join(OUT, name)
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
                           "files": sorted(os.listdir(outdir)),
                           "download": f"/api/download?name={urllib.parse.quote(name)}"})

    def _download(self, q):
        """The bundle as a zip. Over the network there is no other way to reach it."""
        name = q.get("name", [""])[0]
        if not SAFE.match(name):
            return self._json({"error": "bad map name"}, 400)
        outdir = os.path.join(OUT, name)
        if not os.path.isdir(outdir):
            return self._json({"error": "export the map first"}, 404)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(os.listdir(outdir)):
                p = os.path.join(outdir, f)
                if os.path.isfile(p):
                    z.write(p, f"{name}/{f}")
        body = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{name}.zip"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def list_directory(self, path):
        """No directory listings anywhere: they are not part of the app, and they
        advertise tools/ and catalog/ to anyone who gets in."""
        self.send_error(404, "Not Found")
        return None

    # ------------------------------------------------------------------ output
    def end_headers(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        elif IMMUTABLE.match(path):
            # 95 MB of art across 13k files: without this every click refetches
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        msg = fmt % args
        if "/images/" not in msg:          # sheet images are noisy
            sys.stderr.write(msg + "\n")


# Threaded: a single-threaded server stalls the whole app while one 40 MB sheet
# streams, which is survivable on localhost and not over the internet.
class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def seed_maps():
    """A deploy reads WB_MAPS, which is an empty volume the first time it mounts,
    while the maps the image ships sit unused in <root>/maps. Copy them across so a
    fresh deployment opens with the same worlds as a local checkout. A name already
    in the volume is somebody's save and is never overwritten."""
    import shutil
    src = os.path.join(ROOT, "maps")
    if os.path.abspath(src) == os.path.abspath(MAPS) or not os.path.isdir(src):
        return
    for f in sorted(os.listdir(src)):
        # __selftest and friends are test artifacts, not worlds
        if not f.endswith(".json") or f.startswith("__"):
            continue
        dst = os.path.join(MAPS, f)
        if not os.path.exists(dst):
            shutil.copyfile(os.path.join(src, f), dst)


if __name__ == "__main__":
    os.makedirs(MAPS, exist_ok=True)
    seed_maps()
    with Server((HOST, PORT), functools.partial(Handler, directory=ROOT)) as httpd:
        where = "127.0.0.1" if HOST == "127.0.0.1" else HOST
        print(f"WorldBuilder serving {ROOT} on http://{where}:{PORT}")
        print(f"  editor  http://{where}:{PORT}/editor/")
        print(f"  viewer  http://{where}:{PORT}/viewer/")
        print(f"  maps    {MAPS}")
        print(f"  auth    {'on' if (USER and PASS) else 'OFF — set WB_USER/WB_PASS'}")
        httpd.serve_forever()
