from flask import Flask, render_template
 
app = Flask(__name__)
 
# --- Online-Modus (optional) ---
try:
    from flask_socketio import SocketIO
    from online import register_online
    socketio = SocketIO(app)
    register_online(socketio)
except ImportError as e:
    print("Online-Modus deaktiviert:", e)
    socketio = None
# -------------------------------
 
 
@app.route("/")
def index():
    return render_template("index.html")
 
 
if __name__ == "__main__":
    if socketio:
        socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
    else:
        app.run(host="0.0.0.0", port=5000, debug=True)
