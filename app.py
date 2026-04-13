from flask import Flask, render_template_string, request, redirect, url_for, session, send_from_directory, abort
import re
import requests
import datetime
import os
import hashlib
import json
from werkzeug.utils import secure_filename


def load_env_file(path):
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


load_env_file(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

SCHOOL = os.environ.get("SCHOOL", "Gym Bersenbrück")
SERVER = os.environ.get("SERVER", "nessa.webuntis.com")
DATA_PATH = os.path.join(os.path.dirname(__file__), "modyouruntis.json")
LEGACY_DB_PATH = os.path.join(os.path.dirname(__file__), "modyouruntis.db")
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
THEME_NAME_MAX_LENGTH = 40
DEFAULT_BACKGROUND_COLOR = "#f4f6ff"
DEFAULT_BACKGROUND_OPACITY = 100
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
MAX_BG_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APP_PORT", "5000"))
APP_DEBUG = env_bool("APP_DEBUG", default=True)


def default_data_store():
    return {"next_theme_id": 1, "themes": [], "lesson_styles": []}


def load_data_store():
    if not os.path.exists(DATA_PATH):
        return default_data_store()

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return default_data_store()

    if not isinstance(data, dict):
        return default_data_store()

    data.setdefault("next_theme_id", 1)
    data.setdefault("themes", [])
    data.setdefault("lesson_styles", [])

    for theme in data["themes"]:
        theme.setdefault("background_color", DEFAULT_BACKGROUND_COLOR)
        theme.setdefault("background_opacity", DEFAULT_BACKGROUND_OPACITY)
        theme.setdefault("background_image", None)

    return data


def save_data_store(data):
    tmp_path = DATA_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DATA_PATH)


def migrate_legacy_db_if_needed(data):
    if data["themes"] or data["lesson_styles"] or not os.path.exists(LEGACY_DB_PATH):
        return data

    try:
        import sqlite3

        with sqlite3.connect(LEGACY_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            themes = conn.execute(
                "SELECT id, username, name, is_active, created_at FROM themes"
            ).fetchall()
            lesson_styles = conn.execute(
                "SELECT theme_id, lesson_key, bg_color, text_color, border_radius FROM lesson_styles"
            ).fetchall()
    except Exception:
        return data

    data["themes"] = [
        {
            "id": int(row["id"]),
            "username": row["username"],
            "name": row["name"],
            "is_active": int(row["is_active"]),
            "created_at": row["created_at"],
            "background_color": DEFAULT_BACKGROUND_COLOR,
            "background_opacity": DEFAULT_BACKGROUND_OPACITY,
        }
        for row in themes
    ]
    data["lesson_styles"] = [
        {
            "theme_id": int(row["theme_id"]),
            "lesson_key": row["lesson_key"],
            "bg_color": row["bg_color"],
            "text_color": row["text_color"],
            "border_radius": int(row["border_radius"]),
        }
        for row in lesson_styles
    ]
    max_theme_id = max((theme["id"] for theme in data["themes"]), default=0)
    data["next_theme_id"] = max_theme_id + 1
    return data


def init_db():
    data = load_data_store()
    data = migrate_legacy_db_if_needed(data)
    save_data_store(data)


def ensure_default_theme(username):
    data = load_data_store()
    has_theme = any(theme["username"] == username for theme in data["themes"])
    if has_theme:
        return

    theme_id = int(data["next_theme_id"])
    data["themes"].append(
        {
            "id": theme_id,
            "username": username,
            "name": "Default",
            "is_active": 1,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "background_color": DEFAULT_BACKGROUND_COLOR,
            "background_opacity": DEFAULT_BACKGROUND_OPACITY,
            "background_image": None,
        }
    )
    data["next_theme_id"] = theme_id + 1

    default_styles = [
        {"lesson_key": "subject:34", "bg_color": "#00ffff", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:38", "bg_color": "#7322ec", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:43", "bg_color": "#296053", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:17", "bg_color": "#bf1d1d", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:32", "bg_color": "#6a4672", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:11", "bg_color": "#da7a0b", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:18", "bg_color": "#61fb0e", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:163", "bg_color": "#ff004c", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:1", "bg_color": "#2aed1d", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:44", "bg_color": "#c124ff", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:7", "bg_color": "#00fac8", "text_color": "#ffffff", "border_radius": 12},
        {"lesson_key": "subject:51", "bg_color": "#6a2930", "text_color": "#ffffff", "border_radius": 12},
    ]
    for style in default_styles:
        data["lesson_styles"].append({"theme_id": theme_id, **style})

    save_data_store(data)


def get_user_themes(username):
    data = load_data_store()
    rows = [
        {"id": t["id"], "name": t["name"], "is_active": t["is_active"]}
        for t in data["themes"]
        if t["username"] == username
    ]
    return sorted(rows, key=lambda item: item["name"].lower())


def get_active_theme(username):
    data = load_data_store()
    user_themes = [t for t in data["themes"] if t["username"] == username]
    for theme in user_themes:
        if int(theme.get("is_active", 0)) == 1:
            return {
                "id": theme["id"],
                "name": theme["name"],
                "background_color": theme.get(
                    "background_color", DEFAULT_BACKGROUND_COLOR
                ),
                "background_opacity": theme.get(
                    "background_opacity", DEFAULT_BACKGROUND_OPACITY
                ),
                "background_image": theme.get("background_image"),
            }

    if user_themes:
        fallback = sorted(user_themes, key=lambda t: int(t["id"]))[0]
        fallback_id = int(fallback["id"])
        for theme in data["themes"]:
            if theme["username"] == username:
                theme["is_active"] = 1 if int(theme["id"]) == fallback_id else 0
        save_data_store(data)
        return {
            "id": fallback["id"],
            "name": fallback["name"],
            "background_color": fallback.get(
                "background_color", DEFAULT_BACKGROUND_COLOR
            ),
            "background_opacity": fallback.get(
                "background_opacity", DEFAULT_BACKGROUND_OPACITY
            ),
            "background_image": fallback.get("background_image"),
        }
    return None


def get_theme_styles(theme_id):
    data = load_data_store()
    rows = [
        style
        for style in data["lesson_styles"]
        if int(style["theme_id"]) == int(theme_id)
    ]
    return {
        r["lesson_key"]: {
            "bg_color": r["bg_color"],
            "text_color": r["text_color"],
            "border_radius": r["border_radius"],
        }
        for r in rows
    }


def create_theme(username, name):
    cleaned = (name or "").strip()
    if not cleaned:
        return
    cleaned = cleaned[:THEME_NAME_MAX_LENGTH]

    data = load_data_store()
    exists = any(
        t["username"] == username and t["name"] == cleaned for t in data["themes"]
    )
    if exists:
        return

    for theme in data["themes"]:
        if theme["username"] == username:
            theme["is_active"] = 0

    data["themes"].append(
        {
            "id": int(data["next_theme_id"]),
            "username": username,
            "name": cleaned,
            "is_active": 1,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "background_color": DEFAULT_BACKGROUND_COLOR,
            "background_opacity": DEFAULT_BACKGROUND_OPACITY,
            "background_image": None,
        }
    )
    data["next_theme_id"] = int(data["next_theme_id"]) + 1
    save_data_store(data)


def set_active_theme(username, theme_id):
    data = load_data_store()
    owns_theme = any(
        int(t["id"]) == int(theme_id) and t["username"] == username
        for t in data["themes"]
    )
    if not owns_theme:
        return

    for theme in data["themes"]:
        if theme["username"] == username:
            theme["is_active"] = 1 if int(theme["id"]) == int(theme_id) else 0
    save_data_store(data)


def delete_theme(username, theme_id):
    data = load_data_store()
    user_themes = [t for t in data["themes"] if t["username"] == username]
    if len(user_themes) <= 1:
        return False

    target = next(
        (t for t in user_themes if int(t["id"]) == int(theme_id)),
        None,
    )
    if not target:
        return False

    was_active = int(target.get("is_active", 0)) == 1
    delete_id = int(target["id"])
    old_image = target.get("background_image")

    data["themes"] = [
        t
        for t in data["themes"]
        if not (t["username"] == username and int(t["id"]) == delete_id)
    ]
    data["lesson_styles"] = [
        style for style in data["lesson_styles"] if int(style["theme_id"]) != delete_id
    ]

    remaining = sorted(
        [t for t in data["themes"] if t["username"] == username],
        key=lambda t: int(t["id"]),
    )

    if remaining:
        if was_active or not any(int(t.get("is_active", 0)) == 1 for t in remaining):
            first_id = int(remaining[0]["id"])
            for theme in data["themes"]:
                if theme["username"] == username:
                    theme["is_active"] = 1 if int(theme["id"]) == first_id else 0

    save_data_store(data)
    if old_image:
        _remove_bg_image_file(old_image)
    return True


def set_active_theme_background(username, background_color, background_opacity=None):
    active_theme = get_active_theme(username)
    if not active_theme:
        return

    safe_background = sanitize_hex_color(background_color, DEFAULT_BACKGROUND_COLOR)
    if background_opacity is not None:
        try:
            safe_opacity = max(0, min(100, int(background_opacity)))
        except (TypeError, ValueError):
            safe_opacity = DEFAULT_BACKGROUND_OPACITY
    else:
        safe_opacity = None

    data = load_data_store()
    target_id = int(active_theme["id"])
    for theme in data["themes"]:
        if theme["username"] == username and int(theme["id"]) == target_id:
            theme["background_color"] = safe_background
            if safe_opacity is not None:
                theme["background_opacity"] = safe_opacity
            break
    save_data_store(data)


def sanitize_hex_color(value, fallback):
    if not value:
        return fallback
    value = value.strip()
    if len(value) == 7 and value.startswith("#"):
        try:
            int(value[1:], 16)
            return value.lower()
        except ValueError:
            return fallback
    return fallback


_SAFE_IMAGE_EXTENSIONS = {
    "jpg": "jpg",
    "jpeg": "jpeg",
    "png": "png",
    "webp": "webp",
    "gif": "gif",
}


_BG_IMAGE_FILENAME_RE = re.compile(r"^bg_\d+\.(?:jpg|jpeg|png|webp|gif)$")


def _is_valid_bg_image_filename(filename):
    """Return True only for filenames matching the expected background image pattern."""
    return bool(filename and _BG_IMAGE_FILENAME_RE.match(filename))



    raw_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return raw_ext in _SAFE_IMAGE_EXTENSIONS


def _safe_extension_from_filename(filename):
    """Return a sanitized extension from our literal allowlist, or None."""
    raw_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _SAFE_IMAGE_EXTENSIONS.get(raw_ext)


def _remove_bg_image_file(filename):
    if not filename:
        return
    path = os.path.join(UPLOADS_DIR, filename)
    try:
        os.remove(path)
    except OSError:
        pass


def save_active_theme_background_image(username, file_storage):
    active_theme = get_active_theme(username)
    if not active_theme:
        return False, "Kein aktives Theme gefunden."

    original_filename = file_storage.filename or ""
    safe_ext = _safe_extension_from_filename(original_filename)
    if safe_ext is None:
        return False, "Ungültiges Dateiformat. Erlaubt: jpg, jpeg, png, webp, gif."

    data, over_limit = _read_limited(file_storage, MAX_BG_IMAGE_BYTES)
    if over_limit:
        return False, "Datei zu groß. Maximale Größe: 8 MB."

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    theme_id = int(active_theme["id"])
    new_filename = f"bg_{theme_id}.{safe_ext}"

    # Remove any existing image for this theme (may have a different extension).
    db = load_data_store()
    for theme in db["themes"]:
        if theme["username"] == username and int(theme["id"]) == theme_id:
            old_image = theme.get("background_image")
            if old_image and old_image != new_filename:
                _remove_bg_image_file(old_image)
            break

    dest = os.path.join(UPLOADS_DIR, new_filename)
    with open(dest, "wb") as fh:
        fh.write(data)

    for theme in db["themes"]:
        if theme["username"] == username and int(theme["id"]) == theme_id:
            theme["background_image"] = new_filename
            break
    save_data_store(db)
    return True, None


def remove_active_theme_background_image(username):
    active_theme = get_active_theme(username)
    if not active_theme:
        return

    theme_id = int(active_theme["id"])
    data = load_data_store()
    old_image = None
    for theme in data["themes"]:
        if theme["username"] == username and int(theme["id"]) == theme_id:
            old_image = theme.get("background_image")
            theme["background_image"] = None
            break
    save_data_store(data)
    _remove_bg_image_file(old_image)


def _read_limited(file_storage, limit):
    """Read up to `limit` bytes from file_storage.

    Returns ``(data, over_limit)`` where ``over_limit`` is True when the stream
    contained more than ``limit`` bytes.
    """
    chunks = []
    total = 0
    over_limit = False
    while True:
        chunk = file_storage.stream.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            over_limit = True
            break
        chunks.append(chunk)
    return b"".join(chunks), over_limit


def save_lesson_style(username, lesson_key, bg_color, text_color, border_radius):
    active_theme = get_active_theme(username)
    if not active_theme:
        return

    radius = 12
    try:
        radius = max(0, min(24, int(border_radius)))
    except (TypeError, ValueError):
        radius = 12

    safe_bg = sanitize_hex_color(bg_color, "#3498db")
    safe_text = sanitize_hex_color(text_color, "#ffffff")

    data = load_data_store()
    theme_id = int(active_theme["id"])
    existing = next(
        (
            style
            for style in data["lesson_styles"]
            if int(style["theme_id"]) == theme_id and style["lesson_key"] == lesson_key
        ),
        None,
    )

    if existing:
        existing["bg_color"] = safe_bg
        existing["text_color"] = safe_text
        existing["border_radius"] = radius
    else:
        data["lesson_styles"].append(
            {
                "theme_id": theme_id,
                "lesson_key": lesson_key,
                "bg_color": safe_bg,
                "text_color": safe_text,
                "border_radius": radius,
            }
        )
    save_data_store(data)


def login_untis(username, password):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {
        "id": "1",
        "method": "authenticate",
        "params": {"user": username, "password": password, "client": "ModYourUntis"},
        "jsonrpc": "2.0",
    }
    r = requests.post(url, json=payload)
    data = r.json()
    if "result" in data:
        return data["result"]
    return None


def get_subjects(session_id):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {"id": 1, "method": "getSubjects", "params": {}, "jsonrpc": "2.0"}
    cookies = {"JSESSIONID": session_id}
    r = requests.post(url, json=payload, cookies=cookies)
    return {s["id"]: s.get("longName", "???") for s in r.json().get("result", [])}


def get_teachers(session_id):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {"id": 2, "method": "getTeachers", "params": {}, "jsonrpc": "2.0"}
    cookies = {"JSESSIONID": session_id}
    r = requests.post(url, json=payload, cookies=cookies)
    return {t["id"]: t.get("longName", "") for t in r.json().get("result", [])}


def get_rooms(session_id):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {"id": 3, "method": "getRooms", "params": {}, "jsonrpc": "2.0"}
    cookies = {"JSESSIONID": session_id}
    r = requests.post(url, json=payload, cookies=cookies)
    return {r["id"]: r.get("name", "") for r in r.json().get("result", [])}


def get_timetable(session_id, user_id, start, end, user_type=5):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {
        "id": "2",
        "method": "getTimetable",
        "params": {
            "id": user_id,
            "type": user_type,
            "startDate": start,
            "endDate": end,
        },
        "jsonrpc": "2.0",
    }
    cookies = {"JSESSIONID": session_id}
    r = requests.post(url, json=payload, cookies=cookies)
    return r.json().get("result", [])


def get_timegrid_units(session_id):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {"id": 4, "method": "getTimegridUnits", "params": {}, "jsonrpc": "2.0"}
    cookies = {"JSESSIONID": session_id}

    try:
        r = requests.post(url, json=payload, cookies=cookies)
        return r.json().get("result", [])
    except Exception:
        return []


def generate_colors(subjects):
    colors = {}
    base_colors = [
        "#1abc9c",
        "#3498db",
        "#9b59b6",
        "#e67e22",
        "#e74c3c",
        "#2ecc71",
        "#f1c40f",
        "#34495e",
        "#16a085",
        "#2980b9",
    ]
    for i, sub in enumerate(subjects.values()):
        colors[sub] = base_colors[i % len(base_colors)]
    return colors


def format_time(value):
    try:
        text = f"{int(value):04d}"
        return f"{text[:2]}:{text[2:]}"
    except (TypeError, ValueError):
        return "--:--"


init_db()


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        result = login_untis(username, password)
        if result:
            session["session_id"] = result["sessionId"]
            session["personId"] = result["personId"]
            session["username"] = username
            ensure_default_theme(username)
            return redirect(url_for("timetable"))
        return "❌ Login fehlgeschlagen"

    return render_template_string(
        """
    <html>
    <head>
      <title>ModYourUntis | Login</title>
      <style>
        :root { color-scheme: light; }
        body {
          margin: 0;
          font-family: 'Inter', 'Segoe UI', sans-serif;
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          background: radial-gradient(circle at top right, #86a8ff 0%, #5f6fff 30%, #1d1f3f 100%);
          color: #1f2a44;
        }
        .card {
          width: min(420px, 92vw);
          background: rgba(255,255,255,0.95);
          backdrop-filter: blur(8px);
          border-radius: 20px;
          padding: 28px;
          box-shadow: 0 20px 45px rgba(17, 20, 58, .25);
        }
        h1 { margin: 0 0 8px; color: #283b80; }
        p { margin: 0 0 24px; color: #5b6183; }
        label { display:block; margin: 12px 0 6px; font-weight:600; }
        input {
          width: 100%;
          box-sizing: border-box;
          padding: 12px;
          border-radius: 12px;
          border: 1px solid #d4d8eb;
          font-size: 15px;
        }
        button {
          margin-top: 16px;
          width: 100%;
          border: 0;
          border-radius: 12px;
          padding: 12px;
          background: linear-gradient(90deg, #4f6df5, #7f58ff);
          color: white;
          font-weight: 700;
          cursor: pointer;
          font-size: 15px;
        }
      </style>
      <script>
        function saveUsername() {
          localStorage.setItem("username", document.getElementById("username").value);
        }
        window.addEventListener("DOMContentLoaded", function() {
          if(localStorage.getItem("username")){
            document.getElementById("username").value = localStorage.getItem("username");
          }
          document.getElementById("loginForm").addEventListener("submit", saveUsername);
        });
      </script>
    </head>
    <body>
      <div class="card">
        <h1>ModYourUntis</h1>
        <p>Dein persönlicher Untis-Stundenplan im eigenen Design.</p>
        <form id="loginForm" method="POST">
          <label for="username">Benutzername</label>
          <input id="username" name="username" placeholder="Benutzername" required>
          <label for="password">Passwort</label>
          <input id="password" type="password" name="password" placeholder="Passwort" required>
          <button type="submit">Login</button>
        </form>
      </div>
    </body>
    </html>
    """
    )


@app.route("/theme/create", methods=["POST"])
def theme_create():
    username = session.get("username")
    if not username:
        return redirect(url_for("index"))
    create_theme(username, request.form.get("theme_name", ""))
    return redirect(url_for("timetable"))


@app.route("/theme/activate", methods=["POST"])
def theme_activate():
    username = session.get("username")
    if not username:
        return redirect(url_for("index"))
    theme_id = request.form.get("theme_id")
    try:
        set_active_theme(username, int(theme_id))
    except (TypeError, ValueError):
        pass
    return redirect(url_for("timetable"))


@app.route("/theme/delete", methods=["POST"])
def theme_delete():
    username = session.get("username")
    if not username:
        return redirect(url_for("index"))

    theme_id = request.form.get("theme_id")
    try:
        delete_theme(username, int(theme_id))
    except (TypeError, ValueError):
        pass
    return redirect(url_for("timetable"))


@app.route("/theme/background", methods=["POST"])
def theme_background():
    username = session.get("username")
    if not username:
        return redirect(url_for("index"))

    set_active_theme_background(
        username,
        request.form.get("background_color", ""),
        request.form.get("background_opacity"),
    )
    return redirect(url_for("timetable"))


@app.route("/theme/background-image", methods=["POST"])
def theme_background_image():
    username = session.get("username")
    if not username:
        return redirect(url_for("index"))

    file = request.files.get("background_image")
    if not file or not file.filename:
        return redirect(url_for("timetable"))

    ok, error = save_active_theme_background_image(username, file)
    if not ok:
        return f"❌ {error}", 400
    return redirect(url_for("timetable"))


@app.route("/theme/background-image/remove", methods=["POST"])
def theme_background_image_remove():
    username = session.get("username")
    if not username:
        return redirect(url_for("index"))

    remove_active_theme_background_image(username)
    return redirect(url_for("timetable"))


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    username = session.get("username")
    if not username:
        abort(403)

    safe = secure_filename(filename)
    if not safe or safe != filename or not _is_valid_bg_image_filename(safe):
        abort(404)

    # Verify the requesting user owns a theme whose background image matches.
    data = load_data_store()
    if not any(
        t["username"] == username and t.get("background_image") == safe
        for t in data["themes"]
    ):
        abort(403)

    return send_from_directory(UPLOADS_DIR, safe)


@app.route("/lesson-style/save", methods=["POST"])
def lesson_style_save():
    username = session.get("username")
    if not username:
        return redirect(url_for("index"))

    lesson_key = request.form.get("lesson_key", "").strip()
    if lesson_key:
        save_lesson_style(
            username,
            lesson_key,
            request.form.get("bg_color", "#3498db"),
            request.form.get("text_color", "#ffffff"),
            request.form.get("border_radius", "12"),
        )
    return redirect(url_for("timetable"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/timetable")
def timetable():
    session_id = session.get("session_id")
    user_id = session.get("personId")
    username = session.get("username")
    if not session_id or not user_id or not username:
        return redirect(url_for("index"))

    ensure_default_theme(username)
    active_theme = get_active_theme(username)
    themes = get_user_themes(username)
    styles = get_theme_styles(active_theme["id"]) if active_theme else {}
    active_background_color = (
        active_theme.get("background_color", DEFAULT_BACKGROUND_COLOR)
        if active_theme
        else DEFAULT_BACKGROUND_COLOR
    )
    active_background_opacity = (
        active_theme.get("background_opacity", DEFAULT_BACKGROUND_OPACITY)
        if active_theme
        else DEFAULT_BACKGROUND_OPACITY
    )
    active_background_opacity_css = round(active_background_opacity / 100, 2)
    active_background_image = active_theme.get("background_image") if active_theme else None
    if active_background_image and not _is_valid_bg_image_filename(active_background_image):
        active_background_image = None

    try:
        week_offset = int(request.args.get("week", "0"))
    except ValueError:
        week_offset = 0

    today = datetime.date.today()
    monday = (
        today
        - datetime.timedelta(days=today.weekday())
        + datetime.timedelta(weeks=week_offset)
    )
    friday = monday + datetime.timedelta(days=4)
    start = int(monday.strftime("%Y%m%d"))
    end = int(friday.strftime("%Y%m%d"))

    subjects = get_subjects(session_id)
    teachers = get_teachers(session_id)
    rooms = get_rooms(session_id)
    colors = generate_colors(subjects)

    timetable_data = get_timetable(session_id, user_id, start, end, user_type=5)
    timegrid_units = get_timegrid_units(session_id)

    days = {1: "Montag", 2: "Dienstag", 3: "Mittwoch", 4: "Donnerstag", 5: "Freitag"}
    plan = {d: {} for d in days}
    time_labels = {}

    for entry in timetable_data:
        day = entry.get("date")
        if not day:
            continue

        dt = datetime.datetime.strptime(str(day), "%Y%m%d")
        weekday = dt.isoweekday()
        if weekday not in days:
            continue

        start_time = entry.get("startTime")
        end_time = entry.get("endTime")
        su_id = entry.get("su", [{}])[0].get("id")
        te_id = entry.get("te", [{}])[0].get("id")
        ro_id = entry.get("ro", [{}])[0].get("id")

        subject = subjects.get(su_id, "???")
        teacher = teachers.get(te_id, "")
        room = rooms.get(ro_id, "")
        code = entry.get("code", "")

        if code == "irregular":
            teacher = entry.get("te", [{}])[0].get("longName", teacher)

        entry_id = entry.get("id") or entry.get("lessonId") or ""

        # Stable key per class/subject so edits apply to all matching lessons.
        if su_id is not None:
            lesson_key = f"subject:{su_id}"
        else:
            lesson_key = f"subject-name:{subject.strip().lower()}"

        # Backward compatibility: styles previously saved per lesson instance.
        legacy_raw_lesson_key = json.dumps(
            {
                "username": username,
                "weekday": weekday,
                "start_time": start_time,
                "end_time": end_time,
                "subject": subject,
                "teacher": teacher,
                "room": room,
                "entry_id": entry_id,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        legacy_lesson_key = hashlib.sha256(
            legacy_raw_lesson_key.encode("utf-8")
        ).hexdigest()

        if code == "cancelled":
            default_bg = "#e74c3c"
        elif code == "irregular":
            default_bg = "#e67e22"
        else:
            default_bg = colors.get(subject, "#999999")

        style_override = styles.get(lesson_key) or styles.get(legacy_lesson_key, {})
        display_bg = style_override.get("bg_color", default_bg)
        text_color = style_override.get("text_color", "#ffffff")
        border_radius = style_override.get("border_radius", 12)

        lesson = {
            "subject": subject,
            "teacher": teacher,
            "room": room,
            "start": format_time(start_time),
            "end": format_time(end_time),
            "code": code,
            "lesson_key": lesson_key,
            "display_bg": display_bg,
            "text_color": text_color,
            "border_radius": border_radius,
        }

        time_labels[start_time] = {
            "start": format_time(start_time),
            "end": format_time(end_time),
        }

        if start_time not in plan[weekday]:
            plan[weekday][start_time] = []
        plan[weekday][start_time].append(lesson)

    grid_slots = []
    for unit in timegrid_units:
        start_time = unit.get("startTime")
        end_time = unit.get("endTime")
        if start_time is None or end_time is None:
            continue
        grid_slots.append((start_time, end_time))

    # Use school period grid to keep empty lessons visible (for example 6th and 8th with empty 7th).
    if grid_slots:
        grid_slots = sorted(set(grid_slots), key=lambda item: item[0])
        times = [slot[0] for slot in grid_slots]
        for start_time, end_time in grid_slots:
            time_labels.setdefault(
                start_time,
                {"start": format_time(start_time), "end": format_time(end_time)},
            )
    else:
        times = sorted({t for d in plan.values() for t in d.keys()})

    for day_plan in plan.values():
        for start_time in times:
            day_plan.setdefault(start_time, [])

    html_template = """
    <html>
    <head>
      <title>ModYourUntis | Stundenplan</title>
      <script>
        (function() {
          const key = 'preferred-theme';
          let saved = null;
          try {
            saved = localStorage.getItem(key);
          } catch (e) {
            saved = null;
          }

          const fromSystem = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
          const theme = saved === 'dark' || saved === 'light' ? saved : fromSystem;
          document.documentElement.setAttribute('data-theme', theme);
          document.documentElement.style.colorScheme = theme;
        })();
      </script>
      <style>
        :root {
          --bg: {{ active_background_color }};
          --bg-gradient-end: {{ active_background_color }};
          --bg-opacity: {{ active_background_opacity_css }};
          --surface: #ffffff;
          --text: #263355;
          --muted: #6f7aa3;
          --elevated: #fbfcff;
          --time-bg: #f2f5ff;
          --control-border: #d6ddff;
          --control-bg: #ffffff;
          --control-text: #263355;
          --control-shadow: 0 6px 18px rgba(44, 64, 138, 0.08);
          --table-shadow: 0 8px 25px rgba(28, 44, 102, 0.10);
          --link-bg: #e9eeff;
          --link-text: #4f6df5;
          --primary: #4f6df5;
        }
        :root[data-theme="dark"] {
          --surface: #1a233f;
          --text: #dde6ff;
          --muted: #9fb0e0;
          --elevated: #151d35;
          --time-bg: #253154;
          --control-border: #334675;
          --control-bg: #1f2a49;
          --control-text: #dde6ff;
          --control-shadow: 0 10px 20px rgba(4, 8, 20, 0.35);
          --table-shadow: 0 14px 30px rgba(4, 8, 20, 0.45);
          --link-bg: #22325f;
          --link-text: #d7e2ff;
          --primary: #7f9dff;
        }
        * { box-sizing: border-box; }
        body {
          font-family: 'Inter', 'Segoe UI', sans-serif;
          margin: 0;
          padding: 24px;
          color: var(--text);
        }
        body::before {
          content: '';
          position: fixed;
          inset: 0;
          z-index: -1;
          background: linear-gradient(180deg, var(--bg) 0%, var(--bg-gradient-end) 70%);
          {% if active_background_image %}
          background-image: url("{{ url_for('uploaded_file', filename=active_background_image)|urlencode }}");
          background-size: cover;
          background-attachment: fixed;
          background-position: center;
          {% endif %}
          opacity: var(--bg-opacity);
        }
        .topbar {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .brand h1 { margin: 0; font-size: 1.6rem; color: var(--primary); }
        .brand small { color: var(--muted); }
        .controls {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          align-items: center;
        }
        .controls form {
          display: flex;
          gap: 8px;
          align-items: center;
          background: var(--surface);
          padding: 8px;
          border-radius: 12px;
          box-shadow: var(--control-shadow);
        }
        input, select, button {
          border: 1px solid var(--control-border);
          border-radius: 10px;
          padding: 8px 10px;
          font-size: 14px;
          background: var(--control-bg);
          color: var(--control-text);
        }
        button {
          background: var(--primary);
          color: white;
          border: none;
          cursor: pointer;
          font-weight: 600;
        }
        .logout {
          text-decoration: none;
          color: var(--link-text);
          font-weight: 600;
          background: var(--link-bg);
          padding: 8px 12px;
          border-radius: 10px;
        }
        .theme-toggle {
          border: 1px solid var(--control-border);
          background: var(--link-bg);
          color: var(--link-text);
          border-radius: 10px;
          padding: 8px 12px;
          font-weight: 600;
          cursor: pointer;
        }
        .btn-danger {
          background: #c0392b;
          color: #ffffff;
        }
        .table-wrap {
          background: var(--surface);
          border-radius: 16px;
          box-shadow: var(--table-shadow);
          overflow-x: auto;
          padding: 8px;
        }
        table {
          width: 100%;
          border-collapse: separate;
          border-spacing: 6px;
          table-layout: fixed;
        }
        th, td {
          text-align: center;
          vertical-align: top;
        }
        th {
          padding: 10px;
          color: var(--muted);
          font-size: 0.9rem;
        }
        td.time {
          background: var(--time-bg);
          color: var(--muted);
          font-weight: 700;
          border-radius: 10px;
          width: 90px;
          padding: 8px;
        }
        td.slot {
          background: var(--elevated);
          border-radius: 12px;
          min-height: 72px;
          padding: 4px;
        }
        .lesson {
          margin: 4px 0;
          padding: 10px;
          color: #fff;
          font-size: 0.82rem;
          line-height: 1.25rem;
          box-shadow: 0 4px 10px rgba(9, 20, 56, 0.23);
          transition: transform 0.15s ease, box-shadow 0.15s ease;
          cursor: pointer;
          position: relative;
        }
        .lesson:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 16px rgba(9, 20, 56, 0.30);
        }
        .cancelled { text-decoration: line-through; }
        .edit-tag {
          position: absolute;
          right: 8px;
          top: 5px;
          font-size: 10px;
          opacity: .82;
        }

        .modal {
          display: none;
          position: fixed;
          inset: 0;
          background: rgba(10, 16, 44, 0.55);
          z-index: 1000;
          align-items: center;
          justify-content: center;
          padding: 16px;
        }
        .modal-content {
          width: min(420px, 95vw);
          background: var(--surface);
          border-radius: 16px;
          padding: 18px;
          box-shadow: 0 20px 30px rgba(0,0,0,.2);
        }
        .modal-content h3 { margin: 0 0 12px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .grid label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
        .modal-actions {
          margin-top: 14px;
          display: flex;
          justify-content: flex-end;
          gap: 8px;
        }
        .btn-secondary {
          background: var(--link-bg);
          color: var(--link-text);
        }
      </style>
      <script>
        const THEME_STORAGE_KEY = 'preferred-theme';

        function getSystemTheme() {
          return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }

        function updateThemeToggleLabel(theme) {
          const button = document.getElementById('themeToggle');
          if (!button) return;
          button.innerText = theme === 'dark' ? '☀️' : '🌑';
        }

        function applyTheme(theme) {
          const finalTheme = theme === 'dark' ? 'dark' : 'light';
          document.documentElement.setAttribute('data-theme', finalTheme);
          document.documentElement.style.colorScheme = finalTheme;
          updateThemeToggleLabel(finalTheme);
        }

        function getInitialTheme() {
          let saved = null;
          try {
            saved = localStorage.getItem(THEME_STORAGE_KEY);
          } catch (e) {
            saved = null;
          }
          if (saved === 'dark' || saved === 'light') return saved;
          return getSystemTheme();
        }

        function toggleTheme() {
          const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
          const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
          try {
            localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
          } catch (e) {
            // Ignore storage errors and still switch for current session.
          }
          applyTheme(nextTheme);
        }

        function initializeTheme() {
          applyTheme(getInitialTheme());

          const themeToggle = document.getElementById('themeToggle');
          if (themeToggle) {
            themeToggle.addEventListener('click', toggleTheme);
          }

          const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
          const onSystemThemeChange = (event) => {
            let saved = null;
            try {
              saved = localStorage.getItem(THEME_STORAGE_KEY);
            } catch (e) {
              saved = null;
            }
            if (saved) return;
            applyTheme(event.matches ? 'dark' : 'light');
          };

          if (typeof mediaQuery.addEventListener === 'function') {
            mediaQuery.addEventListener('change', onSystemThemeChange);
          } else if (typeof mediaQuery.addListener === 'function') {
            mediaQuery.addListener(onSystemThemeChange);
          }
        }

        function openLessonEditor(lessonKey, subject, bgColor, textColor, radius) {
          document.getElementById('editorModal').style.display = 'flex';
          document.getElementById('edit_subject').innerText = subject;
          document.getElementById('lesson_key').value = lessonKey;
          document.getElementById('bg_color').value = bgColor;
          document.getElementById('text_color').value = textColor;
          document.getElementById('border_radius').value = radius;
        }
        function closeLessonEditor() {
          document.getElementById('editorModal').style.display = 'none';
        }
        function initializeLessonEditors() {
          document.querySelectorAll('.lesson').forEach((el) => {
            el.addEventListener('click', function() {
              openLessonEditor(
                this.dataset.lessonKey,
                this.dataset.subject,
                this.dataset.bgColor,
                this.dataset.textColor,
                this.dataset.borderRadius
              );
            });
          });
          document.getElementById('editorModal').addEventListener('click', function(event) {
            if (event.target === this) closeLessonEditor();
          });
          document.getElementById('closeEditorButton').addEventListener('click', closeLessonEditor);
          document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') closeLessonEditor();
          });
        }

        function initializePage() {
          initializeTheme();
          initializeLessonEditors();
        }

        document.addEventListener('DOMContentLoaded', initializePage);
      </script>
    </head>
    <body>
      <div class="topbar">
        <div class="brand">
          <h1>ModYourUntis</h1>
          <small>Eingeloggt als {{ username }}{% if active_theme %} • Theme: {{ active_theme.name }}{% endif %}</small>
          <br>
          <small>Woche: {{ week_start }} - {{ week_end }}</small>
        </div>
        <div class="controls">
          <button type="button" id="themeToggle" class="theme-toggle">Dunkelmodus</button>
          <a class="logout" href="{{ url_for('timetable', week=week_offset-1) }}">◀ Vorige Woche</a>
          <a class="logout" href="{{ url_for('timetable', week=week_offset+1) }}">Nächste Woche ▶</a>
          <form method="POST" action="{{ url_for('theme_activate') }}">
            <select name="theme_id" required>
              {% for theme in themes %}
                <option value="{{ theme.id }}" {% if theme.is_active %}selected{% endif %}>{{ theme.name }}</option>
              {% endfor %}
            </select>
            <button type="submit">Theme laden</button>
            <button type="submit" formaction="{{ url_for('theme_delete') }}" formmethod="POST" class="btn-danger">Theme löschen</button>
          </form>
          <form method="POST" action="{{ url_for('theme_background') }}">
            <input type="color" name="background_color" value="{{ active_background_color }}" title="Hintergrundfarbe">
            <label style="display:flex;align-items:center;gap:4px;font-size:13px;">
              <input type="range" name="background_opacity" min="0" max="100" value="{{ active_background_opacity }}"
                aria-label="Hintergrundtransparenz"
                style="width:80px;cursor:pointer;"
                oninput="this.nextElementSibling.textContent=this.value+'%'">
              <span>{{ active_background_opacity }}%</span>
            </label>
            <button type="submit">Hintergrundfarbe</button>
          </form>
          <form method="POST" action="{{ url_for('theme_background_image') }}" enctype="multipart/form-data">
            <input type="file" name="background_image" accept=".jpg,.jpeg,.png,.webp,.gif" required title="Hintergrundbild hochladen">
            <button type="submit">Bild hochladen</button>
          </form>
          {% if active_background_image %}
          <form method="POST" action="{{ url_for('theme_background_image_remove') }}">
            <button type="submit" class="btn-danger">Bild entfernen</button>
          </form>
          {% endif %}
          <form method="POST" action="{{ url_for('theme_create') }}">
            <input name="theme_name" maxlength="{{ theme_name_max_length }}" placeholder="Neues Theme" required>
            <button type="submit">Theme erstellen</button>
          </form>
          <a class="logout" href="{{ url_for('logout') }}">Logout</a>
        </div>
      </div>

      <div class="table-wrap">
        <table>
          <tr>
            <th>Zeit</th>
            {% for d in days.values() %}<th>{{ d }}</th>{% endfor %}
          </tr>
          {% for t in times %}
            <tr>
              <td class="time">{{ time_labels[t].start }}-{{ time_labels[t].end }}</td>
              {% for wd in days.keys() %}
                <td class="slot">
                  {% for lesson in plan[wd].get(t, []) %}
                    <div
                      class="lesson {% if lesson.code == 'cancelled' %}cancelled{% endif %}"
                      style="background: {{ lesson.display_bg }}; color: {{ lesson.text_color }}; border-radius: {{ lesson.border_radius }}px;"
                      data-lesson-key="{{ lesson.lesson_key }}"
                      data-subject="{{ lesson.subject }}"
                      data-bg-color="{{ lesson.display_bg }}"
                      data-text-color="{{ lesson.text_color }}"
                      data-border-radius="{{ lesson.border_radius }}"
                    >
                      <span class="edit-tag">anpassen</span>
                      {{ lesson.subject }}<br>
                      {{ lesson.teacher }}{% if lesson.code == 'cancelled' %}<br><strong>Entfällt</strong>{% endif %}
                      <br>{{ lesson.room }}
                    </div>
                  {% endfor %}
                </td>
              {% endfor %}
            </tr>
          {% endfor %}
        </table>
      </div>

      <div class="modal" id="editorModal">
        <div class="modal-content">
          <h3>Stunde anpassen: <span id="edit_subject"></span></h3>
          <form method="POST" action="{{ url_for('lesson_style_save') }}">
            <input type="hidden" id="lesson_key" name="lesson_key">
            <div class="grid">
              <label>Hintergrundfarbe
                <input type="color" id="bg_color" name="bg_color" value="#3498db">
              </label>
              <label>Textfarbe
                <input type="color" id="text_color" name="text_color" value="#ffffff">
              </label>
              <label>Rundung (0-24 px)
                <input type="number" id="border_radius" name="border_radius" min="0" max="24" value="12">
              </label>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn-secondary" id="closeEditorButton">Abbrechen</button>
              <button type="submit">Speichern</button>
            </div>
          </form>
        </div>
      </div>
    </body>
    </html>
    """

    return render_template_string(
        html_template,
        plan=plan,
        days=days,
        times=times,
        time_labels=time_labels,
        themes=themes,
        active_theme=active_theme,
        username=username,
        theme_name_max_length=THEME_NAME_MAX_LENGTH,
        active_background_color=active_background_color,
        active_background_opacity=active_background_opacity,
        active_background_opacity_css=active_background_opacity_css,
        active_background_image=active_background_image,
        week_offset=week_offset,
        week_start=monday.strftime("%d.%m.%Y"),
        week_end=friday.strftime("%d.%m.%Y"),
    )


if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT, debug=APP_DEBUG)
