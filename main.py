from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import join_room, leave_room, send, SocketIO
import random
from string import ascii_uppercase

app = Flask(__name__)
app.config["SECRET_KEY"] = "1234"
socketio = SocketIO(app)

# stores active rooms with member count and message history.
rooms = {}

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
    return jsonify(list(rooms.keys()))

# home page route. handles room creation and joining existing rooms.
@app.route("/", methods=["GET", "POST"])
def home():
    session.clear() # clear session data when user visits home page
    if request.method =="POST":
        name = request.form.get("name") # get username input.
        code = request.form.get("code") # get room code input.
        join = request.form.get("join", False) # checks if user wants to join a room.
        create = request.form.get("create", False) # checks if user wants to create a new room.

        # input validation.
        if not name:
            return render_template("home.html", error="Please enter name.", code=code, name=name, available_rooms=list(rooms.keys()))
        
        if join != False and not code:
            return render_template("home.html", error="Please enter room code.", code=code, name=name, available_rooms=list(rooms.keys()))
        
        room = code
        if create != False: # creates a new room.
            room = generate_unique_code(4)
            rooms[room] = {"members": 0, "messages": []}
        elif code not in rooms: # check if the room already exists.
            return render_template("home.html", error="Room not found.", code=code, name=name, available_rooms=list(rooms.keys()))
        
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
    
    return render_template("room.html", code=room, messages=rooms[room]["messages"])

# handle incoming chat messages through websocket and display them in the room.
@socketio.on("message")
def message(data):
    room = session.get("room")
    if room not in rooms:
        return
    
    content = {
         "name": session.get("name"),
         "message": data["data"]
    }
    send(content, to=room) # send message to the room.
    rooms[room]["messages"].append(content) # save message in chat history.
    print(f"{session.get('name')} said: {data['data']}")

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

    if room in rooms:
        rooms[room]["members"] -= 1 # decrease the member count.
        if rooms[room]["members"] <= 0: # delete room if empty.
            del rooms[room]
        
        send({"name": name, "message": "has left the room."}, to=room) # send leave message event to the room.
        print(f"{name} left room {room}.")

# initialization.
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", debug=True)
