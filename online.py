"""
Online-Modus für 1v1 Battle: Relay-Server auf Basis von Flask-SocketIO.
Der Server rechnet nichts vom Spiel, er verwaltet nur Räume und leitet Nachrichten weiter.

Neu: Lock gegen Race Conditions, Wiederverbinden (Token + Schonfrist), Zuschauer,
Limits gegen Missbrauch, robuster Ping.

Events (Client -> Server): create, join {code}, rejoin {code, token}, watch {code},
                           leave, relay {...}, ping_t
Events (Server -> Client): room_created {code, token}, joined {code, token}, rejoined {code, role},
                           watching {code}, peer_joined, peer_lost, peer_back, peer_left,
                           join_error {msg}, msg {...}
"""

import json
import random
import secrets
import threading
import time

from flask import request
from flask_socketio import emit, join_room

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
GRACE_SECONDS = 25          # so lange bleibt ein Platz nach Verbindungsabbruch reserviert
MAX_MSG_CHARS = 20000       # größere Nachrichten werden verworfen
MAX_MSGS_PER_SEC = 200
MAX_JOIN_FAILS = 10         # pro Minute und Verbindung
MAX_SPECTATORS = 20

lock = threading.RLock()
rooms = {}      # code -> {"p": {"host": slot, "guest": slot|None}, "spec": set()}
sid_info = {}   # sid -> {"code", "role"}   role: host | guest | spec
rate = {}       # sid -> [window_start, count]
fails = {}      # sid -> [window_start, count]
# slot = {"sid": str|None, "token": str, "timer": Timer|None}


def _new_code():
    while True:
        code = "".join(random.choices(ALPHABET, k=4))
        if code not in rooms:
            return code


def _slot(sid):
    return {"sid": sid, "token": secrets.token_urlsafe(16), "timer": None}


def _too_many(table, sid, limit, window):
    now = time.time()
    w = table.get(sid)
    if not w or now - w[0] >= window:
        w = table[sid] = [now, 0]
    w[1] += 1
    return w[1] > limit


def register_online(socketio):

    def _dissolve(code, skip_sid=None):
        """Raum auflösen, alle übrigen Beteiligten informieren (Lock muss gehalten werden)."""
        room = rooms.pop(code, None)
        if not room:
            return
        sids = set(room["spec"])
        for slot in room["p"].values():
            if slot:
                if slot["timer"]:
                    slot["timer"].cancel()
                if slot["sid"]:
                    sids.add(slot["sid"])
        for s in sids:
            sid_info.pop(s, None)
            if s != skip_sid:
                socketio.emit("peer_left", {}, to=s)

    def _expire(code, role, token):
        with lock:
            room = rooms.get(code)
            slot = room and room["p"].get(role)
            if slot and slot["token"] == token and slot["sid"] is None:
                _dissolve(code)

    def _other_sid(room, role):
        other = room["p"].get("guest" if role == "host" else "host")
        return other["sid"] if other else None

    def _leave(sid):
        """Verbindung verlässt den Raum endgültig (leave / neuer Raum)."""
        info = sid_info.pop(sid, None)
        if not info:
            return
        room = rooms.get(info["code"])
        if not room:
            return
        if info["role"] == "spec":
            room["spec"].discard(sid)
        else:
            _dissolve(info["code"], skip_sid=sid)

    @socketio.on("create")
    def on_create():
        with lock:
            _leave(request.sid)
            code = _new_code()
            slot = _slot(request.sid)
            rooms[code] = {"p": {"host": slot, "guest": None}, "spec": set()}
            sid_info[request.sid] = {"code": code, "role": "host"}
            join_room(code)
            emit("room_created", {"code": code, "token": slot["token"]})

    @socketio.on("join")
    def on_join(data=None):
        code = str((data or {}).get("code", "")).strip().upper()
        with lock:
            if _too_many(fails, request.sid, MAX_JOIN_FAILS, 60):
                emit("join_error", {"msg": "Zu viele Versuche. Bitte kurz warten."})
                return
            room = rooms.get(code)
            if not room:
                emit("join_error", {"msg": "Raum nicht gefunden."})
                return
            host = room["p"]["host"]
            if host["sid"] == request.sid:
                emit("join_error", {"msg": "Das ist dein eigener Raum."})
                return
            if room["p"]["guest"]:
                emit("join_error", {"msg": "Der Raum ist schon voll."})
                return
            _leave(request.sid)
            slot = _slot(request.sid)
            room["p"]["guest"] = slot
            sid_info[request.sid] = {"code": code, "role": "guest"}
            join_room(code)
            fails.pop(request.sid, None)
            emit("joined", {"code": code, "token": slot["token"]})
            if host["sid"]:
                emit("peer_joined", {}, to=host["sid"])

    @socketio.on("rejoin")
    def on_rejoin(data=None):
        data = data or {}
        code = str(data.get("code", "")).strip().upper()
        token = str(data.get("token", ""))
        with lock:
            if _too_many(fails, request.sid, MAX_JOIN_FAILS, 60):
                emit("join_error", {"msg": "Zu viele Versuche. Bitte kurz warten."})
                return
            room = rooms.get(code)
            role = None
            if room:
                for r, slot in room["p"].items():
                    if slot and secrets.compare_digest(slot["token"], token):
                        role = r
            if not role:
                emit("join_error", {"msg": "Wiederverbinden nicht möglich."})
                return
            slot = room["p"][role]
            if slot["timer"]:
                slot["timer"].cancel()
                slot["timer"] = None
            if slot["sid"] and slot["sid"] != request.sid:
                sid_info.pop(slot["sid"], None)
            slot["sid"] = request.sid
            sid_info[request.sid] = {"code": code, "role": role}
            join_room(code)
            emit("rejoined", {"code": code, "role": role})
            other = _other_sid(room, role)
            if other:
                emit("peer_back", {}, to=other)

    @socketio.on("watch")
    def on_watch(data=None):
        code = str((data or {}).get("code", "")).strip().upper()
        with lock:
            if _too_many(fails, request.sid, MAX_JOIN_FAILS, 60):
                emit("join_error", {"msg": "Zu viele Versuche. Bitte kurz warten."})
                return
            room = rooms.get(code)
            if not room:
                emit("join_error", {"msg": "Raum nicht gefunden."})
                return
            if len(room["spec"]) >= MAX_SPECTATORS:
                emit("join_error", {"msg": "Zu viele Zuschauer."})
                return
            _leave(request.sid)
            room["spec"].add(request.sid)
            sid_info[request.sid] = {"code": code, "role": "spec"}
            join_room(code)
            emit("watching", {"code": code})

    @socketio.on("leave")
    def on_leave():
        with lock:
            _leave(request.sid)

    @socketio.on("relay")
    def on_relay(data=None):
        sid = request.sid
        with lock:
            info = sid_info.get(sid)
            if not info or info["role"] == "spec":      # Zuschauer dürfen nicht senden
                return
            if _too_many(rate, sid, MAX_MSGS_PER_SEC, 1):
                return
            code = info["code"]
        try:
            if len(json.dumps(data)) > MAX_MSG_CHARS:
                return
        except (TypeError, ValueError):
            return
        emit("msg", data, to=code, include_self=False)

    @socketio.on("ping_t")
    def on_ping(*args):
        return True

    @socketio.on("disconnect")
    def on_disconnect(*args):
        sid = request.sid
        with lock:
            rate.pop(sid, None)
            fails.pop(sid, None)
            info = sid_info.pop(sid, None)
            if not info:
                return
            code, role = info["code"], info["role"]
            room = rooms.get(code)
            if not room:
                return
            if role == "spec":
                room["spec"].discard(sid)
                return
            slot = room["p"][role]
            if slot["sid"] != sid:
                return
            slot["sid"] = None                      # Platz reservieren, Schonfrist starten
            other = _other_sid(room, role)
            if other:
                socketio.emit("peer_lost", {"grace": GRACE_SECONDS}, to=other)
            t = threading.Timer(GRACE_SECONDS, _expire, args=(code, role, slot["token"]))
            t.daemon = True
            slot["timer"] = t
            t.start()
