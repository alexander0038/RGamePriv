# Beispiel – NUR die markierten Teile in deine echte app.py übernehmen!
# Bot- und 1v1-Modus laufen auch dann, wenn flask-socketio nicht installiert ist.
from flask_socketio import SocketIO
from online import register_online

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")
register_online(socketio)

app = Flask(__name__)

# --- Online-Modus (optional) ---
try:
    from flask_socketio import SocketIO
    from online import register_online
    # async_mode="threading": passt zu gunicorn --threads (siehe unten) und
    # verhindert, dass eventlet/gevent automatisch gewählt wird und hängt.
    socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")
    register_online(socketio)
except ImportError as e:
    print("Online-Modus deaktiviert:", e)
    socketio = None
# -------------------------------


@app.route("/")
def index():
    return render_template("index.html")


# Render Start Command:   gunicorn -w 1 --threads 100 app:app
# (genau 1 Worker, weil die Räume im Arbeitsspeicher liegen)

if __name__ == "__main__":      # nur für lokales Testen
    if socketio:
        socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
    else:
        app.run(host="0.0.0.0", port=5000, debug=True)
