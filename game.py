from flask import Flask, render_template
 
app = Flask(__name__)
 
# --- Online-Modus (optional) ---
try:
    from flask_socketio import SocketIO
    from online import register_online
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
 
if __name__ == "__main__":
    if socketio:
        socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
    else:
        app.run(host="0.0.0.0", port=5000, debug=True)
 
