import random
from flask import request
from flask_socketio import emit, join_room

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne I/O/0/1 (Verwechslungsgefahr)
rooms = {}  # code -> { host : sid, guest : sid | None}
sid_room = {}  # sid -> code

def _new_code():
    while True:
        code = "".join(random.choices(ALPHABET, k=4))
        if code not in rooms:
            return code

def _leave(sid):
    # Raum auflösen und den anderen Spieler benachrichtigen.
    code = sid_room.pop(sid, None)
    if not code:
        return
    room = rooms.pop(code, None)
    if not room:
        return
    for other in (room["host"], room["guest"]):
        if other and other != sid:
            sid_room.pop(other, None)
            emit("peer_left", {}, to=other)

def register_online(socketio):
    @socketio.on("create")
    def on_create():
        _leave(request.sid)
        code = _new_code()
        rooms[code] = {"host": request.sid, "guest": None}
        sid_room[request.sid] = code
        join_room(code)
        emit("room_created", {"code": code})

    @socketio.on("join")
    def on_join(data):
        code = str((data or {}).get("code", "")).strip().upper()
        room = rooms.get(code)
        if not room:
            emit("join_error", {"msg": "Raum nicht gefunden."})
            return
        if room["guest"]:
            emit("join_error", {"msg": "Der Raum ist schon voll."})
            return
        if room["host"] == request.sid:
            emit("join_error", {"msg": "Das ist dein eigener Raum."})
            return
            
        _leave(request.sid)
        room["guest"] = request.sid
        sid_room[request.sid] = code
        join_room(code)
        
        emit("joined", {"code": code})
        emit("peer_joined", {}, to=room["host"])

    @socketio.on("relay")
    def on_relay(data):
        code = sid_room.get(request.sid)
        if code:
            emit("msg", data, to=code, include_self=False)

    @socketio.on("disconnect")
    def on_disconnect(*args):
        _leave(request.sid)
