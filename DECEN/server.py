"""DECEN websocket chat server.

This module hosts the DECEN chat service and keeps all dependencies in the
Python standard library plus ``websockets``.  It intentionally avoids global
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
from websockets.exceptions import ConnectionClosed

APP_DIR = Path(__file__).resolve().parent
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765
PASSWORD_ITERATIONS = 240_000
MAX_MESSAGE_LENGTH = 1_000
HISTORY_LIMIT = 50


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
# CHAT SERVER
# =========================
@dataclass
class ChatServer:
    store: UserStore
    connected_clients: dict[Any, dict[str, Any]] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)

    async def handler(self, websocket: Any) -> None:
        logging.info("Client connected from %s", websocket.remote_address)

        try:
            user, created = await self.authenticate(websocket)
            if user is None:
                return

            self.connected_clients[websocket] = user
            await self.send_welcome(websocket, user, created)
            await self.broadcast_system(f"{user['username']} joined DECEN.")

            async for message in websocket:
                await self.process_message(websocket, message)

        except ConnectionClosed:
            logging.info("Client disconnected.")
        except Exception:
            logging.exception("Unexpected client handler error")
        finally:
            user = self.connected_clients.pop(websocket, None)
            if user:
                await self.broadcast_system(f"{user['username']} left DECEN.")

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
            "SYSTEM | Type /help for commands, /who for online users, and /quit to exit."
        )

        if self.history:
            await websocket.send("SYSTEM | Recent messages:")
            for line in self.history[-10:]:
                await websocket.send(line)

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

        formatted = f"[{utc_stamp()}] {sender['username']} ({sender['uid']}): {message}"
        logging.info("Broadcast: %s", formatted)
        self.history.append(formatted)
        del self.history[:-HISTORY_LIMIT]
        await self.broadcast(formatted)

    async def handle_command(
        self, websocket: Any, user: dict[str, Any], command: str
    ) -> None:
        command_name = command.split(maxsplit=1)[0].lower()

        if command_name == "/help":
            await websocket.send(
                "SYSTEM | Commands: /help, /who, /me <action>, /clear, /quit"
            )
        elif command_name == "/who":
            names = sorted(u["username"] for u in self.connected_clients.values())
            await websocket.send(f"SYSTEM | Online ({len(names)}): {', '.join(names)}")
        elif command_name == "/me":
            action = command.partition(" ")[2].strip()
            if not action:
                await websocket.send("SYSTEM | Usage: /me <action>")
                return
            formatted = f"[{utc_stamp()}] * {user['username']} {action}"
            self.history.append(formatted)
            del self.history[:-HISTORY_LIMIT]
            await self.broadcast(formatted)
        elif command_name == "/clear":
            await websocket.send("\033cSYSTEM | Local screen cleared.")
        elif command_name == "/quit":
            await websocket.send("SYSTEM | Goodbye.")
            await websocket.close()
        else:
            await websocket.send(
                f"SYSTEM | Unknown command: {command_name}. Try /help."
            )

    async def broadcast_system(self, message: str) -> None:
        if self.connected_clients:
            await self.broadcast(f"SYSTEM | {message}")

    async def broadcast(self, message: str) -> None:
        stale_clients: list[Any] = []
        for client in list(self.connected_clients.keys()):
            try:
                await client.send(message)
            except ConnectionClosed:
                stale_clients.append(client)

        for client in stale_clients:
            self.connected_clients.pop(client, None)


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

    async with websockets.serve(server.handler, args.host, args.port):
        logging.info("DECEN Server running on ws://%s:%s", args.host, args.port)
        logging.info("Using data directory: %s", store.data_dir)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
