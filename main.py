from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import join_room, leave_room, send, emit, SocketIO
import random
from string import ascii_uppercase
from flask_pymongo import PyMongo
from datetime import datetime
import os
from dotenv import load_dotenv

# Flask configuration.
app = Flask(__name__)
app.config["SECRET_KEY"] = "1234"
socketio = SocketIO(app, cors_allowed_origins="*")

# MongoDB configuration.
load_dotenv() # loads environment variables from .env file.
mongo_uri = os.getenv("MONGO_URI")
app.config["MONGO_URI"] = os.getenv("MONGO_URI")
mongo = PyMongo(app)

# try to connect to MongoDB. if it fails, use in-memory database.
mongo = None
try:
    mongo = PyMongo(app)
    print("Connected to MongoDB.")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")

# stores active rooms with member count and message history.
rooms = {
    "GENERAL": {"members": 0, "messages": [], "locked": False, "permanent": True, "creator": "Server"},
    "GAMING": {"members": 0, "messages": [], "locked": False, "permanent": True, "creator": "Server"},
    "POLITICS": {"members": 0, "messages": [], "locked": False, "permanent": True, "creator": "Server"},
}


# generates a unique 4-letter room code.
def generate_unique_code(length):
    while True:
        code = ""
        for _ in range(length):
            code += random.choice(ascii_uppercase)
        
        if code not in rooms: # checks if room code already exists.
            break

    return code

# API endpoint that returns available rooms in JSON.
@app.route("/api/rooms")
def get_rooms():
    unlocked_rooms = [code for code, room_data in rooms.items() if not room_data.get("locked", False)]
    return jsonify(unlocked_rooms)

# home page route. handles room creation and joining existing rooms.
@app.route("/", methods=["GET", "POST"])
def home():
    session.clear() # clear session data when user visits home page
    if request.method =="POST":
        name = request.form.get("name") # get username input.
        code = request.form.get("code") # get room code input.
        join = request.form.get("join", False) # checks if user wants to join a room.
        create = request.form.get("create", False) # checks if user wants to create a new room.
        password = request.form.get("password", "") # Add password field for locked rooms

        # input validation.
        if not name:
            return render_template("home.html", error="Please enter name.", code=code, name=name, available_rooms=list(rooms.keys()))
        
        if join != False and not code:
            return render_template("home.html", error="Please enter room code.", code=code, name=name, available_rooms=list(rooms.keys()))
        
        room = code
        if create != False:  # creates a new room.
            if code in rooms and rooms[code]["permanent"]:
                return render_template("home.html", error="Cannot create a room with the same name as a permanent room.", code=code, name=name, available_rooms=list(rooms.keys()))
            room = generate_unique_code(4)
            rooms[room] = {"members": 0, "messages": [], "locked": False, "password": "", "creator": name, "permanent": False}
        elif code not in rooms:  # check if the room already exists.
            return render_template("home.html", error="Room not found.", code=code, name=name, available_rooms=list(rooms.keys()))
        elif rooms[code]["locked"]:  # check if room is locked.
            if password != rooms[code]["password"]:  # verify password.
                return render_template("home.html", error="Incorrect password.", code=code, name=name, show_password_field=True)
        
        # store room and username in session data and redirect to chat room page.
        session["room"] = room
        session["name"] = name
        return redirect(url_for("room"))

    return render_template("home.html")

# chat room route.
@app.route("/room")
def room():
    room = session.get("room")

    # redirect to home page if session data is missing or room does not exist.
    if room is None or session.get("name") is None or room not in rooms:
        return redirect(url_for("home"))
    
    # load chat rooms history, sorted by timestamp.
    if mongo: # If DB is available, load messages from database.
        history = list(mongo.db.rooms.find({"room": room}).sort("timestamp", 1))
    else: # If DB is not available, load messages from in-memory database.
        history = rooms[room]["messages"]

    # convert ObjectId to string.
    for msg in history:
        msg['_id'] = str(msg['_id'])

    return render_template("room.html", code=room, messages=history)

@app.route("/api/room/<room_code>/lock", methods=["POST"])
def toggle_room_lock(room_code):
    if room_code not in rooms:
        return jsonify({"success": False, "error": "Room not found"})
    
    data = request.get_json()
    name = data.get("name")
    password = data.get("password", "")

    if name != rooms[room_code]["creator"]:
        return jsonify({"success": False, "error": "Only room creator can lock/unlock"})
    
    rooms[room_code]["locked"] = not rooms[room_code]["locked"]
    if rooms[room_code]["locked"]:
        rooms[room_code]["password"] = password

    return jsonify({
        "success": True,
        "locked": rooms[room_code]["locked"],
        "message": f"Room {'locked' if rooms[room_code]['locked'] else 'unlocked'}"
    })

@app.route("/api/room/<room_code>")
def get_room_status(room_code):
    if room_code not in rooms:
        return jsonify({"error": "Room not found"}), 404
    
    return jsonify({
        "code": room_code,
        "locked": rooms[room_code]["locked"],
        "members": rooms[room_code]["members"],
        "creator": rooms[room_code]["creator"]
    })

# handle incoming chat messages through websocket and display them in the room.
@socketio.on("message")
def message(data):
    room = session.get("room")
    if room not in rooms:
        return
    
    content = {
         "name": session.get("name"),
         "message": data["data"],
         "room": room,
         "timestamp": datetime.utcnow().isoformat()
    }

    send(content, to=room) # send message to the room.
    rooms[room]["messages"].append(content) # save message in chat history.

    if mongo: # If DB is available, save message to database.
        mongo.db.rooms.insert_one(content)
    print(f"{session.get('name')}: {data['data']}")

# handle user connection to a room.
@socketio.on("connect")
def connect(auth):
    room = session.get("room")
    name = session.get("name")
    if not room or not name:
        return
    if room not in rooms:
        leave_room(room)
        return
    
    # send join message event when a new user connects to the room.
    join_room(room)
    send({"name": name, "message": "has entered the room"}, to=room)
    rooms[room]["members"] += 1 # increase the room's member count.
    print(f"{name} joined room {room}")

# handle user disconnection from a room and remove them from the room list.
@socketio.on("disconnect")
def disconnect():
    room = session.get("room")
    name = session.get("name")
    leave_room(room) # remove user from the room

    if room in rooms and not rooms[room]["permanent"]:
        rooms[room]["members"] -= 1 # decrease the member count.
        if rooms[room]["members"] <= 0: # delete room if empty.
            del rooms[room]
        
        send({"name": name, "message": "has left the room."}, to=room) # send leave message event to the room.
        print(f"{name} left room {room}.")

# handles leaving rooms
@socketio.on("leave_room")
def handle_leave_room():
    room = session.get("room")
    name = session.get("name")
    if room and name:
        leave_room(room)
        if room in rooms and not rooms[room].get("permanent", False): # permanent rooms do not get deleted.
            rooms[room]["members"] -= 1
            send({"name": name, "message": "has left the room"}, to=room)
            if rooms[room]["members"] <= 0:
                del rooms[room]
        session.clear()

@app.route("/clear_session")
def clear_session():
    session.clear()
    return redirect(url_for("home"))

# initialization.
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", debug=True)