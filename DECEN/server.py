import asyncio
import websockets
import json
import os
import time
import random
import string

connected_clients = {}


# =========================
# ID / KEY GENERATORS
# =========================
def generate_uid():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))


def generate_access_key():
    return "sk-" + ''.join(random.choices(string.ascii_letters + string.digits, k=16))


# =========================
# USER STORAGE
# =========================
def load_users():
    if not os.path.exists("users.json"):
        return []
    with open("users.json", "r") as f:
        return json.load(f)


def save_users(users):
    with open("users.json", "w") as f:
        json.dump(users, f, indent=4)


# =========================
# SERVER HANDLER
# =========================
async def handler(websocket):
    print("Client connected.")

    users = load_users()

    # ---- HANDSHAKE AUTH ----
    await websocket.send("USERNAME:")
    username = await websocket.recv()

    await websocket.send("PASSWORD:")
    password = await websocket.recv()

    user = next((u for u in users if u["username"] == username), None)

    # ---- AUTO CREATE USER ----
    if not user:
        print(f"Creating new user: {username}")

        user = {
            "uid": generate_uid(),
            "username": username,
            "password": password,
            "access_key": generate_access_key(),
            "created": int(time.time())
        }

        users.append(user)
        save_users(users)

        await websocket.send(f"ACCOUNT CREATED | UID: {user['uid']}")

    else:
        # VERIFY PASSWORD
        if user["password"] != password:
            await websocket.send("AUTH FAILED")
            await websocket.close()
            return

        await websocket.send(f"AUTH SUCCESS | UID: {user['uid']}")

    # REGISTER CLIENT
    connected_clients[websocket] = user

    try:
        async for message in websocket:
            sender = connected_clients.get(websocket)

            formatted = f"[{sender['uid']} | {sender['username']}]: {message}"

            print("Broadcast:", formatted)

            # broadcast to all clients
            for client in list(connected_clients.keys()):
                try:
                    await client.send(formatted)
                except:
                    pass

    except:
        pass

    finally:
        connected_clients.pop(websocket, None)
        print("Client disconnected.")


# =========================
# START SERVER
# =========================
async def main():
    async with websockets.serve(handler, "localhost", 8765):
        print("DECEN Server Running on ws://localhost:8765")
        await asyncio.Future()


asyncio.run(main())