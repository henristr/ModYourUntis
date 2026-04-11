from flask import Flask, render_template_string, request, redirect, url_for, session
import requests
import datetime
import sqlite3
import os
import hashlib
import json


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
DB_PATH = os.path.join(os.path.dirname(__file__), "modyouruntis.db")
THEME_NAME_MAX_LENGTH = 40
APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APP_PORT", "5000"))
APP_DEBUG = env_bool("APP_DEBUG", default=True)


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS themes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(username, name)
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lesson_styles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                theme_id INTEGER NOT NULL,
                lesson_key TEXT NOT NULL,
                bg_color TEXT NOT NULL,
                text_color TEXT NOT NULL,
                border_radius INTEGER NOT NULL DEFAULT 12,
                UNIQUE(theme_id, lesson_key),
                FOREIGN KEY(theme_id) REFERENCES themes(id) ON DELETE CASCADE
            )
        """
        )
        conn.commit()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_default_theme(username):
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM themes WHERE username = ? LIMIT 1",
            (username,),
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO themes(username, name, is_active, created_at) VALUES (?, ?, 1, ?)",
                (
                    username,
                    "Default",
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                ),
            )
            conn.commit()


def get_user_themes(username):
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, is_active FROM themes WHERE username = ? ORDER BY name",
            (username,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_theme(username):
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, name FROM themes WHERE username = ? AND is_active = 1 LIMIT 1",
            (username,),
        ).fetchone()
        if row:
            return dict(row)

        fallback = conn.execute(
            "SELECT id, name FROM themes WHERE username = ? ORDER BY id LIMIT 1",
            (username,),
        ).fetchone()
        if fallback:
            conn.execute(
                "UPDATE themes SET is_active = 0 WHERE username = ?", (username,)
            )
            conn.execute(
                "UPDATE themes SET is_active = 1 WHERE id = ?", (fallback["id"],)
            )
            conn.commit()
            return dict(fallback)
    return None


def get_theme_styles(theme_id):
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT lesson_key, bg_color, text_color, border_radius FROM lesson_styles WHERE theme_id = ?",
            (theme_id,),
        ).fetchall()
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
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO themes(username, name, is_active, created_at) VALUES (?, ?, 0, ?)",
            (
                username,
                cleaned[:THEME_NAME_MAX_LENGTH],
                datetime.datetime.now(datetime.timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def set_active_theme(username, theme_id):
    with get_db_connection() as conn:
        own = conn.execute(
            "SELECT id FROM themes WHERE id = ? AND username = ?",
            (theme_id, username),
        ).fetchone()
        if not own:
            return
        conn.execute("UPDATE themes SET is_active = 0 WHERE username = ?", (username,))
        conn.execute("UPDATE themes SET is_active = 1 WHERE id = ?", (theme_id,))
        conn.commit()


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

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO lesson_styles(theme_id, lesson_key, bg_color, text_color, border_radius)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(theme_id, lesson_key)
            DO UPDATE SET
                bg_color = excluded.bg_color,
                text_color = excluded.text_color,
                border_radius = excluded.border_radius
            """,
            (active_theme["id"], lesson_key, safe_bg, safe_text, radius),
        )
        conn.commit()


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

    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    friday = monday + datetime.timedelta(days=4)
    start = int(monday.strftime("%Y%m%d"))
    end = int(friday.strftime("%Y%m%d"))

    subjects = get_subjects(session_id)
    teachers = get_teachers(session_id)
    rooms = get_rooms(session_id)
    colors = generate_colors(subjects)

    timetable_data = get_timetable(session_id, user_id, start, end, user_type=5)

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
        raw_lesson_key = json.dumps(
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
        lesson_key = hashlib.sha256(raw_lesson_key.encode("utf-8")).hexdigest()

        if code == "cancelled":
            default_bg = "#e74c3c"
        elif code == "irregular":
            default_bg = "#e67e22"
        else:
            default_bg = colors.get(subject, "#999999")

        style_override = styles.get(lesson_key, {})
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

    times = sorted({t for d in plan.values() for t in d.keys()})

    html_template = """
    <html>
    <head>
      <title>ModYourUntis | Stundenplan</title>
      <style>
        :root {
          --bg: #f4f6ff;
          --surface: #ffffff;
          --text: #263355;
          --muted: #6f7aa3;
        }
        * { box-sizing: border-box; }
        body {
          font-family: 'Inter', 'Segoe UI', sans-serif;
          margin: 0;
          padding: 24px;
          background: linear-gradient(180deg, #eef2ff 0%, #f8f9ff 70%);
          color: var(--text);
        }
        .topbar {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .brand h1 { margin: 0; font-size: 1.6rem; color: #3047a6; }
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
          box-shadow: 0 6px 18px rgba(44, 64, 138, 0.08);
        }
        input, select, button {
          border: 1px solid #d6ddff;
          border-radius: 10px;
          padding: 8px 10px;
          font-size: 14px;
          background: white;
        }
        button {
          background: #4f6df5;
          color: white;
          border: none;
          cursor: pointer;
          font-weight: 600;
        }
        .logout {
          text-decoration: none;
          color: #4f6df5;
          font-weight: 600;
          background: #e9eeff;
          padding: 8px 12px;
          border-radius: 10px;
        }
        .table-wrap {
          background: var(--surface);
          border-radius: 16px;
          box-shadow: 0 8px 25px rgba(28, 44, 102, 0.10);
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
          color: #4a5686;
          font-size: 0.9rem;
        }
        td.time {
          background: #f2f5ff;
          color: #586189;
          font-weight: 700;
          border-radius: 10px;
          width: 90px;
          padding: 8px;
        }
        td.slot {
          background: #fbfcff;
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
          background: white;
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
          background: #e9eeff;
          color: #3550be;
        }
      </style>
      <script>
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
        document.addEventListener('DOMContentLoaded', initializeLessonEditors);
      </script>
    </head>
    <body>
      <div class="topbar">
        <div class="brand">
          <h1>ModYourUntis</h1>
          <small>Eingeloggt als {{ username }}{% if active_theme %} • Theme: {{ active_theme.name }}{% endif %}</small>
        </div>
        <div class="controls">
          <form method="POST" action="{{ url_for('theme_activate') }}">
            <select name="theme_id" required>
              {% for theme in themes %}
                <option value="{{ theme.id }}" {% if theme.is_active %}selected{% endif %}>{{ theme.name }}</option>
              {% endfor %}
            </select>
            <button type="submit">Theme laden</button>
          </form>
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
    )


if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT, debug=APP_DEBUG)
