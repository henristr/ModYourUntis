from flask import Flask, render_template_string, request, redirect, url_for, session
import requests
import datetime

app = Flask(__name__)
app.secret_key = "mega-geheimes-passwort"

SCHOOL = "Gym Bersenbrück"
SERVER = "nessa.webuntis.com"

def login_untis(username, password):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {
        "id": "1",
        "method": "authenticate",
        "params": {"user": username, "password": password, "client": "FlaskUntisApp"},
        "jsonrpc": "2.0"
    }
    r = requests.post(url, json=payload)
    data = r.json()
    if "result" in data:
        return data["result"]
    return None

def get_subjects(session_id):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {"id":1,"method":"getSubjects","params":{},"jsonrpc":"2.0"}
    cookies = {"JSESSIONID": session_id}
    r = requests.post(url,json=payload,cookies=cookies)
    return {s["id"]: s.get("longName","???") for s in r.json().get("result",[])}

def get_teachers(session_id):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {"id":2,"method":"getTeachers","params":{},"jsonrpc":"2.0"}
    cookies = {"JSESSIONID": session_id}
    r = requests.post(url,json=payload,cookies=cookies)
    return {t["id"]: t.get("longName","") for t in r.json().get("result",[])}

def get_rooms(session_id):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {"id":3,"method":"getRooms","params":{},"jsonrpc":"2.0"}
    cookies = {"JSESSIONID": session_id}
    r = requests.post(url,json=payload,cookies=cookies)
    return {r["id"]: r.get("name","") for r in r.json().get("result",[])}

def get_timetable(session_id, user_id, start, end, user_type=5):
    url = f"https://{SERVER}/WebUntis/jsonrpc.do?school={SCHOOL}"
    payload = {
        "id": "2",
        "method": "getTimetable",
        "params": {"id": user_id, "type": user_type, "startDate": start, "endDate": end},
        "jsonrpc": "2.0"
    }
    cookies = {"JSESSIONID": session_id}
    r = requests.post(url, json=payload, cookies=cookies)
    return r.json().get("result", [])

def generate_colors(subjects):
    colors = {}
    base_colors = [
        "#1abc9c", "#3498db", "#9b59b6", "#e67e22", "#e74c3c",
        "#2ecc71", "#f1c40f", "#34495e", "#16a085", "#2980b9"
    ]
    for i, sub in enumerate(subjects.values()):
        colors[sub] = base_colors[i % len(base_colors)]
    return colors

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
            return redirect(url_for("timetable"))
        else:
            return "❌ Login fehlgeschlagen"
    
    return render_template_string("""
    <html>
    <head>
      <title>Login</title>
      <style>
        body { font-family: sans-serif; text-align: center; padding: 40px; background: #f5f5f5; }
        input { margin: 10px; padding: 10px; font-size: 16px; }
        button { padding: 10px 20px; font-size: 16px; }
      </style>
      <script>
        window.onload = function() {
          if(localStorage.getItem("username")){
            document.getElementById("username").value = localStorage.getItem("username");
          }
        }
        function saveUsername(){
          localStorage.setItem("username", document.getElementById("username").value);
        }
      </script>
    </head>
    <body>
      <h2>Login WebUntis</h2>
      <form method="POST" onsubmit="saveUsername()">
        <input id="username" name="username" placeholder="Benutzername" required><br>
        <input type="password" name="password" placeholder="Passwort" required><br>
        <button type="submit">Login</button>
      </form>
    </body>
    </html>
    """)

@app.route("/timetable")
def timetable():
    session_id = session.get("session_id")
    user_id = session.get("personId")
    if not session_id or not user_id:
        return redirect(url_for("index"))

    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    friday = monday + datetime.timedelta(days=4)
    start = int(monday.strftime("%Y%m%d"))
    end = int(friday.strftime("%Y%m%d"))

    subjects = get_subjects(session_id)
    teachers = get_teachers(session_id)
    rooms    = get_rooms(session_id)
    colors   = generate_colors(subjects)

    timetable_data = get_timetable(session_id, user_id, start, end, user_type=5)

    days = {1:"Montag",2:"Dienstag",3:"Mittwoch",4:"Donnerstag",5:"Freitag"}
    plan = {d:{} for d in days}

    for entry in timetable_data:
        day = entry.get("date")
        if not day: continue
        dt = datetime.datetime.strptime(str(day), "%Y%m%d")
        weekday = dt.isoweekday()
        if weekday not in days: continue

        start_time = entry.get("startTime")
        end_time   = entry.get("endTime")
        su_id = entry.get("su", [{}])[0].get("id")
        te_id = entry.get("te", [{}])[0].get("id")
        ro_id = entry.get("ro", [{}])[0].get("id")

        subject = subjects.get(su_id, "???")
        teacher = teachers.get(te_id, "")
        room = rooms.get(ro_id, "")
        color = colors.get(subject, "#999")
        code  = entry.get("code", "")
        # Für Vertretungsstunden könnte man hier den Vertretungslehrer auslesen:
        if code == "irregular":
            # Beispiel: ersetze Lehrername durch Vertretungslehrer
            teacher = entry.get("te", [{}])[0].get("longName", teacher)

        lesson = {
            "subject": subject,
            "teacher": teacher,
            "room": room,
            "color": color,
            "start": f"{str(start_time)[:-2]}:{str(start_time)[-2:]}",
            "end": f"{str(end_time)[:-2]}:{str(end_time)[-2:]}",
            "code": code
        }

        if start_time not in plan[weekday]:
            plan[weekday][start_time] = []
        plan[weekday][start_time].append(lesson)

    times = sorted({t for d in plan.values() for t in d.keys()})
    
    html_template = """
    <html>
    <head>
      <title>Stundenplan</title>
      <style>
        body { font-family: 'Segoe UI', sans-serif; padding: 20px; background: #f0f2f5; }
        h1 { text-align: center; margin-bottom: 20px; color: #333; }
        table { width: 100%; border-collapse: collapse; table-layout: fixed; background: white; box-shadow: 0 2px 10px rgba(0,0,0,0.1); border-radius: 10px; overflow: hidden; }
        th, td { border: 1px solid #ddd; text-align: center; vertical-align: top; padding: 4px; position: relative; }
        th { background: #f7f7f7; font-weight: bold; color: #555; font-size: 14px; }
        td.time { background: #f7f7f7; font-weight: bold; width: 60px; color: #555; }
        td .lesson { margin: 2px 0; padding: 8px; border-radius: 10px; color: white; font-size: 0.85em; line-height: 1.2em; box-shadow: 0 2px 5px rgba(0,0,0,0.2); transition: transform 0.2s, box-shadow 0.2s; }
        td .lesson:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,0,0,0.3); cursor: pointer; }
        .cancelled { text-decoration: line-through; }
      </style>
    </head>
    <body>
      <h1>Mein Stundenplan</h1>
      <table>
        <tr><th>Zeit</th>
        {% for d in days.values() %}<th>{{ d }}</th>{% endfor %}
        </tr>
        {% for t in times %}
          <tr>
            <td class="time">{{ plan[1][t][0].start if plan[1].get(t) else '' }}-{{ plan[1][t][0].end if plan[1].get(t) else '' }}</td>
            {% for wd in days.keys() %}
              <td>
                {% for lesson in plan[wd].get(t, []) %}
                  <div class="lesson {% if lesson.code=='cancelled' %}cancelled{% endif %}" style="
                    {% if lesson.code=='cancelled' %}background:#e74c3c
                    {% elif lesson.code=='irregular' %}background:#e67e22
                    {% else %}background:{{ lesson.color }}{% endif %}">
                    {{ lesson.subject }}<br>
                    {{ lesson.teacher }}{% if lesson.code=='cancelled' %}<br><strong>Entfällt</strong>{% endif %}
                    <br>{{ lesson.room }}
                  </div>
                {% endfor %}
              </td>
            {% endfor %}
          </tr>
        {% endfor %}
      </table>
    </body>
    </html>
    """

    return render_template_string(html_template, plan=plan, days=days, times=times)

if __name__ == "__main__":
    app.run(debug=True)
