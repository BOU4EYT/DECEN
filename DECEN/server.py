"""DECEN websocket chat server.

This module hosts the DECEN chat service and keeps all dependencies in the
Python standard library plus ``websockets``. It intentionally avoids global
runtime configuration so the server can be imported, tested, and started from
custom entry points.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websockets
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

APP_DIR = Path(__file__).resolve().parent
DEFAULT_HOST = os.environ.get("DECEN_HOST", "localhost")
DEFAULT_PORT = int(os.environ.get("PORT", os.environ.get("DECEN_PORT", "8765")))
DEFAULT_ROOM = "lobby"
PASSWORD_ITERATIONS = 240_000
MAX_MESSAGE_LENGTH = 1_000
HISTORY_LIMIT = 50
ROOM_NAME_MIN_LENGTH = 2
ROOM_NAME_MAX_LENGTH = 32


# =========================
# ID / KEY / PASSWORD HELPERS
# =========================
def utc_timestamp() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def utc_stamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%H:%M:%S UTC")


def generate_uid() -> str:
    return os.urandom(6).hex()


def generate_access_key() -> str:
    return "sk-" + os.urandom(18).hex()


def hash_password(password: str, *, salt: bytes | None = None) -> dict[str, Any]:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return {
        "algorithm": "pbkdf2_sha256",
        "iterations": PASSWORD_ITERATIONS,
        "salt": salt.hex(),
        "hash": digest.hex(),
    }


def verify_password(user: dict[str, Any], password: str) -> bool:
    password_hash = user.get("password_hash")
    if password_hash:
        salt = bytes.fromhex(password_hash["salt"])
        expected = bytes.fromhex(password_hash["hash"])
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(password_hash.get("iterations", PASSWORD_ITERATIONS)),
        )
        return hmac.compare_digest(actual, expected)

    # Backward compatibility: existing demo databases stored plaintext passwords.
    return hmac.compare_digest(str(user.get("password", "")), password)


def migrate_password(user: dict[str, Any], password: str) -> bool:
    if user.get("password_hash"):
        return False

    user["password_hash"] = hash_password(password)
    user.pop("password", None)
    return True


# =========================
# STORAGE
# =========================
def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")
    tmp_path.replace(path)


@dataclass
class UserStore:
    data_dir: Path
    users: list[dict[str, Any]] = field(default_factory=list)

    @property
    def users_path(self) -> Path:
        return self.data_dir / "users.json"

    def load(self) -> None:
        if not self.users_path.exists():
            self.users = []
            return

        with self.users_path.open("r", encoding="utf-8") as file:
            self.users = json.load(file)

    def save(self) -> None:
        atomic_write_json(self.users_path, self.users)

    def find(self, username: str) -> dict[str, Any] | None:
        return next((u for u in self.users if u.get("username") == username), None)

    def create(self, username: str, password: str) -> dict[str, Any]:
        user = {
            "uid": generate_uid(),
            "username": username,
            "password_hash": hash_password(password),
            "access_key": generate_access_key(),
            "created": utc_timestamp(),
        }
        self.users.append(user)
        self.save()
        return user


# =========================
# ROOMS
# =========================
@dataclass
class ChatRoom:
    name: str
    admin_uid: str | None = None
    created_by: str | None = None
    created: int = field(default_factory=utc_timestamp)
    members: set[Any] = field(default_factory=set)
    history: list[str] = field(default_factory=list)
    topic: str = ""

    @property
    def admin_label(self) -> str:
        return self.created_by or "server"

    def is_admin(self, user: dict[str, Any]) -> bool:
        return self.admin_uid is not None and user.get("uid") == self.admin_uid

    def append_history(self, message: str) -> None:
        self.history.append(message)
        del self.history[:-HISTORY_LIMIT]


def normalize_room_name(name: str) -> str:
    return name.strip().lower()


def validate_room_name(name: str) -> str | None:
    if not (ROOM_NAME_MIN_LENGTH <= len(name) <= ROOM_NAME_MAX_LENGTH):
        return f"Room names must be {ROOM_NAME_MIN_LENGTH}-{ROOM_NAME_MAX_LENGTH} characters."
    if not name.replace("_", "").replace("-", "").isalnum():
        return "Room names may only contain letters, numbers, underscores, and hyphens."
    return None


def landing_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DECEN Server</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #080b12; color: #f5f7fb; }
    main { width: min(760px, calc(100% - 40px)); padding: 40px; border: 1px solid #263043; border-radius: 24px; background: linear-gradient(145deg, #111827, #0b1020); box-shadow: 0 20px 60px #0008; }
    h1 { margin-top: 0; font-size: clamp(2rem, 6vw, 4rem); letter-spacing: .08em; }
    code, pre { background: #020617; color: #93c5fd; border-radius: 10px; }
    code { padding: .2rem .4rem; }
    pre { overflow-x: auto; padding: 18px; }
    a { color: #67e8f9; }
    .status { display: inline-flex; gap: .5rem; align-items: center; color: #86efac; font-weight: 700; }
    .dot { width: .7rem; height: .7rem; border-radius: 999px; background: #22c55e; box-shadow: 0 0 20px #22c55e; }
  </style>
</head>
<body>
  <main>
    <p class="status"><span class="dot"></span> DECEN websocket server online</p>
    <h1>D.E.C.E.N.</h1>
    <p>This address is a websocket endpoint for the DECEN terminal chat client. Browsers cannot chat here by opening the URL directly, but the server is running.</p>
    <p>Connect from your machine with:</p>
    <pre><code>python DECEN/main.py --url wss://YOUR-FLY-APP.fly.dev</code></pre>
    <p>For local testing, run:</p>
    <pre><code>python DECEN/server.py
python DECEN/main.py --server local</code></pre>
  </main>
</body>
</html>
"""


def http_response(status: int, reason: str, body: str, content_type: str) -> Response:
    encoded = body.encode("utf-8")
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(encoded))
    headers["Cache-Control"] = "no-store"
    return Response(status, reason, headers, encoded)


# =========================
# CHAT SERVER
# =========================
@dataclass
class ChatServer:
    store: UserStore
    connected_clients: dict[Any, dict[str, Any]] = field(default_factory=dict)
    client_rooms: dict[Any, str] = field(default_factory=dict)
    rooms: dict[str, ChatRoom] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rooms[DEFAULT_ROOM] = ChatRoom(name=DEFAULT_ROOM, topic="Welcome to DECEN")

    def process_request(self, _: Any, request: Request) -> Response | None:
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None
        if request.path == "/healthz":
            return http_response(200, "OK", "ok\n", "text/plain; charset=utf-8")
        return http_response(200, "OK", landing_page(), "text/html; charset=utf-8")

    async def handler(self, websocket: Any) -> None:
        logging.info("Client connected from %s", websocket.remote_address)

        try:
            user, created = await self.authenticate(websocket)
            if user is None:
                return

            self.connected_clients[websocket] = user
            self.rooms[DEFAULT_ROOM].members.add(websocket)
            self.client_rooms[websocket] = DEFAULT_ROOM
            await self.send_welcome(websocket, user, created)
            await self.broadcast_room_system(
                DEFAULT_ROOM, f"{user['username']} joined."
            )

            async for message in websocket:
                await self.process_message(websocket, message)

        except ConnectionClosed:
            logging.info("Client disconnected.")
        except Exception:
            logging.exception("Unexpected client handler error")
        finally:
            user = self.connected_clients.pop(websocket, None)
            if user:
                await self.leave_current_room(websocket, user, announce=True)

    async def authenticate(self, websocket: Any) -> tuple[dict[str, Any] | None, bool]:
        await websocket.send("USERNAME:")
        username = (await websocket.recv()).strip()

        await websocket.send("PASSWORD:")
        password = await websocket.recv()

        validation_error = validate_credentials(username, password)
        if validation_error:
            await websocket.send(f"AUTH FAILED | {validation_error}")
            await websocket.close()
            return None, False

        user = self.store.find(username)
        if user is None:
            user = self.store.create(username, password)
            logging.info("Created new user: %s", username)
            return user, True

        if not verify_password(user, password):
            await websocket.send("AUTH FAILED | Invalid username or password.")
            await websocket.close()
            return None, False

        if migrate_password(user, password):
            self.store.save()
            logging.info("Migrated plaintext password for user: %s", username)

        return user, False

    async def send_welcome(
        self, websocket: Any, user: dict[str, Any], created: bool
    ) -> None:
        status = "ACCOUNT CREATED" if created else "AUTH SUCCESS"
        await websocket.send(f"{status} | UID: {user['uid']}")
        await websocket.send(
            "SYSTEM | You are in #lobby. Type /help for room and admin commands."
        )
        await self.send_room_history(websocket, DEFAULT_ROOM)

    async def process_message(self, websocket: Any, raw_message: str) -> None:
        sender = self.connected_clients.get(websocket)
        if sender is None:
            return

        message = raw_message.strip()
        if not message:
            await websocket.send("SYSTEM | Empty messages are not sent.")
            return

        if len(message) > MAX_MESSAGE_LENGTH:
            await websocket.send(
                f"SYSTEM | Message too long ({len(message)}/{MAX_MESSAGE_LENGTH})."
            )
            return

        if message.startswith("/"):
            await self.handle_command(websocket, sender, message)
            return

        room_name = self.client_rooms.get(websocket, DEFAULT_ROOM)
        formatted = (
            f"[{utc_stamp()}] #{room_name} {sender['username']} "
            f"({sender['uid']}): {message}"
        )
        logging.info("Broadcast: %s", formatted)
        self.rooms[room_name].append_history(formatted)
        await self.broadcast_to_room(room_name, formatted)

    async def handle_command(
        self, websocket: Any, user: dict[str, Any], command: str
    ) -> None:
        command_name, _, argument = command.partition(" ")
        command_name = command_name.lower()
        argument = argument.strip()

        if command_name == "/help":
            await websocket.send(
                "SYSTEM | Commands: /help, /rooms, /room, /create <room>, "
                "/join <room>, /leave, /who, /me <action>, /topic [text], "
                "/kick <user>, /close, /clear, /quit"
            )
        elif command_name == "/rooms":
            await self.send_room_list(websocket)
        elif command_name == "/room":
            await self.send_current_room(websocket)
        elif command_name == "/create":
            await self.create_room(websocket, user, argument)
        elif command_name == "/join":
            await self.join_room_command(websocket, argument)
        elif command_name == "/leave":
            await self.leave_room_command(websocket, user)
        elif command_name == "/who":
            await self.send_room_members(websocket)
        elif command_name == "/me":
            await self.send_action(websocket, user, argument)
        elif command_name == "/topic":
            await self.topic_command(websocket, user, argument)
        elif command_name == "/kick":
            await self.kick_user(websocket, user, argument)
        elif command_name == "/close":
            await self.close_room(websocket, user)
        elif command_name == "/clear":
            await websocket.send("\033cSYSTEM | Local screen cleared.")
        elif command_name == "/quit":
            await websocket.send("SYSTEM | Goodbye.")
            await websocket.close()
        else:
            await websocket.send(
                f"SYSTEM | Unknown command: {command_name}. Try /help."
            )

    async def create_room(
        self, websocket: Any, user: dict[str, Any], room_name: str
    ) -> None:
        room_name = normalize_room_name(room_name)
        validation_error = validate_room_name(room_name)
        if validation_error:
            await websocket.send(f"SYSTEM | {validation_error}")
            return
        if room_name in self.rooms:
            await websocket.send(
                f"SYSTEM | Room #{room_name} already exists. Use /join {room_name}."
            )
            return

        self.rooms[room_name] = ChatRoom(
            name=room_name, admin_uid=user["uid"], created_by=user["username"]
        )
        await self.join_room(websocket, room_name)
        await websocket.send(
            f"SYSTEM | You created #{room_name} and are its admin. "
            "Admin commands: /topic <text>, /kick <user>, /close."
        )

    async def join_room_command(self, websocket: Any, room_name: str) -> None:
        room_name = normalize_room_name(room_name)
        if not room_name:
            await websocket.send("SYSTEM | Usage: /join <room>")
            return
        if room_name not in self.rooms:
            await websocket.send(
                f"SYSTEM | Room #{room_name} does not exist. Create it with /create {room_name}."
            )
            return
        await self.join_room(websocket, room_name)

    async def join_room(
        self, websocket: Any, room_name: str, *, announce: bool = True
    ) -> None:
        user = self.connected_clients[websocket]
        current_room = self.client_rooms.get(websocket)
        if current_room == room_name:
            await websocket.send(f"SYSTEM | You are already in #{room_name}.")
            return

        if current_room:
            await self.leave_current_room(websocket, user, announce=announce)

        room = self.rooms[room_name]
        room.members.add(websocket)
        self.client_rooms[websocket] = room_name
        await websocket.send(f"SYSTEM | Joined #{room_name}.")
        if room.topic:
            await websocket.send(f"SYSTEM | Topic: {room.topic}")
        await self.send_room_history(websocket, room_name)
        if announce:
            await self.broadcast_room_system(
                room_name, f"{user['username']} joined #{room_name}."
            )

    async def leave_room_command(self, websocket: Any, user: dict[str, Any]) -> None:
        current_room = self.client_rooms.get(websocket, DEFAULT_ROOM)
        if current_room == DEFAULT_ROOM:
            await websocket.send("SYSTEM | You are already in #lobby.")
            return

        await self.leave_current_room(websocket, user, announce=True)
        await self.join_room(websocket, DEFAULT_ROOM, announce=False)

    async def leave_current_room(
        self, websocket: Any, user: dict[str, Any], *, announce: bool
    ) -> None:
        room_name = self.client_rooms.pop(websocket, None)
        if room_name is None:
            return

        room = self.rooms.get(room_name)
        if room is None:
            return

        room.members.discard(websocket)
        if announce:
            await self.broadcast_room_system(
                room_name, f"{user['username']} left #{room_name}."
            )

        if room_name != DEFAULT_ROOM and not room.members:
            self.rooms.pop(room_name, None)
            logging.info("Removed empty room #%s", room_name)
        elif room_name != DEFAULT_ROOM and room.admin_uid == user.get("uid"):
            await self.transfer_admin(room)

    async def transfer_admin(self, room: ChatRoom) -> None:
        if not room.members:
            return
        new_admin_socket = next(iter(room.members))
        new_admin = self.connected_clients[new_admin_socket]
        room.admin_uid = new_admin["uid"]
        room.created_by = new_admin["username"]
        await self.broadcast_room_system(
            room.name, f"{new_admin['username']} is now admin of #{room.name}."
        )

    async def send_room_list(self, websocket: Any) -> None:
        lines = []
        for name, room in sorted(self.rooms.items()):
            marker = "*" if self.client_rooms.get(websocket) == name else " "
            topic = f" | {room.topic}" if room.topic else ""
            lines.append(
                f"{marker} #{name} ({len(room.members)} online, admin: {room.admin_label}){topic}"
            )
        await websocket.send("SYSTEM | Rooms:\n" + "\n".join(lines))

    async def send_current_room(self, websocket: Any) -> None:
        room_name = self.client_rooms.get(websocket, DEFAULT_ROOM)
        room = self.rooms[room_name]
        await websocket.send(
            f"SYSTEM | Current room: #{room_name} | admin: {room.admin_label} | "
            f"online: {len(room.members)}"
        )
        if room.topic:
            await websocket.send(f"SYSTEM | Topic: {room.topic}")

    async def send_room_members(self, websocket: Any) -> None:
        room_name = self.client_rooms.get(websocket, DEFAULT_ROOM)
        room = self.rooms[room_name]
        names = sorted(
            self.connected_clients[client]["username"] for client in room.members
        )
        await websocket.send(
            f"SYSTEM | #{room_name} online ({len(names)}): {', '.join(names)}"
        )

    async def send_action(
        self, websocket: Any, user: dict[str, Any], action: str
    ) -> None:
        if not action:
            await websocket.send("SYSTEM | Usage: /me <action>")
            return
        room_name = self.client_rooms.get(websocket, DEFAULT_ROOM)
        formatted = f"[{utc_stamp()}] #{room_name} * {user['username']} {action}"
        self.rooms[room_name].append_history(formatted)
        await self.broadcast_to_room(room_name, formatted)

    async def topic_command(
        self, websocket: Any, user: dict[str, Any], topic: str
    ) -> None:
        room_name = self.client_rooms.get(websocket, DEFAULT_ROOM)
        room = self.rooms[room_name]
        if not topic:
            await websocket.send(f"SYSTEM | Topic: {room.topic or 'No topic set.'}")
            return
        if not await self.require_room_admin(websocket, user, room):
            return
        room.topic = topic[:120]
        await self.broadcast_room_system(room_name, f"Topic set to: {room.topic}")

    async def kick_user(
        self, websocket: Any, admin: dict[str, Any], username: str
    ) -> None:
        room_name = self.client_rooms.get(websocket, DEFAULT_ROOM)
        room = self.rooms[room_name]
        if not await self.require_room_admin(websocket, admin, room):
            return
        if room_name == DEFAULT_ROOM:
            await websocket.send("SYSTEM | The lobby cannot use /kick.")
            return
        if not username:
            await websocket.send("SYSTEM | Usage: /kick <username>")
            return

        target_socket = self.find_member_socket(room, username)
        if target_socket is None:
            await websocket.send(f"SYSTEM | {username} is not in #{room_name}.")
            return
        if target_socket == websocket:
            await websocket.send(
                "SYSTEM | Admins cannot kick themselves; use /leave or /close."
            )
            return

        target_user = self.connected_clients[target_socket]
        await self.leave_current_room(target_socket, target_user, announce=False)
        await target_socket.send(
            f"SYSTEM | You were removed from #{room_name} by {admin['username']}."
        )
        await self.join_room(target_socket, DEFAULT_ROOM, announce=False)
        await self.broadcast_room_system(
            room_name, f"{target_user['username']} was removed by an admin."
        )

    async def close_room(self, websocket: Any, user: dict[str, Any]) -> None:
        room_name = self.client_rooms.get(websocket, DEFAULT_ROOM)
        room = self.rooms[room_name]
        if room_name == DEFAULT_ROOM:
            await websocket.send("SYSTEM | The lobby cannot be closed.")
            return
        if not await self.require_room_admin(websocket, user, room):
            return

        members = list(room.members)
        await self.broadcast_room_system(
            room_name, f"#{room_name} was closed by {user['username']}."
        )
        for member in members:
            member_user = self.connected_clients.get(member)
            if member_user is None:
                continue
            self.client_rooms.pop(member, None)
            room.members.discard(member)
            await self.join_room(member, DEFAULT_ROOM, announce=False)
        self.rooms.pop(room_name, None)

    async def require_room_admin(
        self, websocket: Any, user: dict[str, Any], room: ChatRoom
    ) -> bool:
        if room.is_admin(user):
            return True
        await websocket.send(
            f"SYSTEM | Admin only. #{room.name} admin is {room.admin_label}."
        )
        return False

    def find_member_socket(self, room: ChatRoom, username: str) -> Any | None:
        username = username.lower()
        for socket in room.members:
            user = self.connected_clients.get(socket)
            if user and user["username"].lower() == username:
                return socket
        return None

    async def send_room_history(self, websocket: Any, room_name: str) -> None:
        room = self.rooms[room_name]
        if not room.history:
            return
        await websocket.send(f"SYSTEM | Recent messages in #{room_name}:")
        for line in room.history[-10:]:
            await websocket.send(line)

    async def broadcast_room_system(self, room_name: str, message: str) -> None:
        await self.broadcast_to_room(room_name, f"SYSTEM | {message}")

    async def broadcast_to_room(self, room_name: str, message: str) -> None:
        room = self.rooms.get(room_name)
        if room is None:
            return

        stale_clients: list[Any] = []
        for client in list(room.members):
            try:
                await client.send(message)
            except ConnectionClosed:
                stale_clients.append(client)

        for client in stale_clients:
            room.members.discard(client)
            self.connected_clients.pop(client, None)
            self.client_rooms.pop(client, None)


def validate_credentials(username: str, password: str) -> str | None:
    if not (3 <= len(username) <= 24):
        return "Username must be 3-24 characters."
    if not username.replace("_", "").replace("-", "").isalnum():
        return "Username may only contain letters, numbers, underscores, and hyphens."
    if len(password) < 6:
        return "Password must be at least 6 characters."
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the DECEN websocket chat server.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host/IP to bind.")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Port to bind.")
    parser.add_argument(
        "--data-dir",
        default=APP_DIR,
        type=Path,
        help="Directory containing users.json and related DECEN data files.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Server log verbosity.",
    )
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    store = UserStore(Path(args.data_dir))
    store.load()
    server = ChatServer(store)

    async with websockets.serve(
        server.handler, args.host, args.port, process_request=server.process_request
    ):
        logging.info("DECEN Server running on ws://%s:%s", args.host, args.port)
        logging.info("Using data directory: %s", store.data_dir)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
