from flask import Flask, render_template
from flask_socketio import SocketIO
from online import register_online
 
app = Flask(__name__)
socketio = SocketIO(app)
register_online(socketio)
 
 
@app.route("/")
def index():
    return render_template("index.html")
 
 
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
