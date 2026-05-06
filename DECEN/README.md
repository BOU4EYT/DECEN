# DECEN

DECEN is a lightweight terminal-based websocket chat application. It includes a
server (`server.py`) and a client (`main.py`) that can connect to the public
main server, a local server, or any self-hosted DECEN server.

## Highlights

- Chatrooms/group chats: users can `/create`, `/join`, and `/leave` rooms.
- Room admins: the user who creates a room can set `/topic`, `/kick` members,
  and `/close` the room.
- Friendlier terminal client with main/local/custom server selection,
  `--host`, `--port`, `--url`, `--username`, and `--no-animation` options.
- Masked password entry with `getpass`.
- Server-side commands: `/help`, `/rooms`, `/room`, `/create`, `/join`,
  `/leave`, `/who`, `/me`, `/topic`, `/kick`, `/close`, `/clear`, and `/quit`.
- Join/leave system messages and per-room recent message history.
- Safer account storage using PBKDF2 password hashes. Older plaintext demo
  users are migrated automatically after a successful login.
- Configurable server host, port, data directory, and log level.
- Fly.io deployment files for hosting a shared DECEN server.

## Requirements

- Python 3.10+
- [`websockets`](https://websockets.readthedocs.io/)

Install the only runtime dependency:

```bash
python -m pip install -r DECEN/requirements.txt
```

## Quick start: local server

Start the server in one terminal:

```bash
python DECEN/server.py
```

Connect with the client in another terminal and choose `2` for local server:

```bash
python DECEN/main.py
```

You can also skip the prompt and connect directly to a local server:

```bash
python DECEN/main.py --server local --username alice --no-animation
```

## Connect to the main server or your own server

The client can connect three ways:

```bash
# Prompt for main/local/custom server choice
python DECEN/main.py

# Connect to the configured main DECEN server
python DECEN/main.py --server main

# Connect directly to any hosted DECEN server
python DECEN/main.py --url wss://your-decen-app.fly.dev
```

Set `DECEN_MAIN_SERVER` to change the default used by `--server main`:

```bash
export DECEN_MAIN_SERVER=wss://your-decen-app.fly.dev
python DECEN/main.py --server main
```

## Useful server options

```bash
python DECEN/server.py --host 0.0.0.0 --port 8765 --data-dir DECEN --log-level INFO
```

The server also respects `DECEN_HOST`, `DECEN_PORT`, and Fly.io's `PORT`
environment variable.

## Chatroom commands

| Command | Description |
| --- | --- |
| `/help` | Show available commands. |
| `/rooms` | List available rooms, admins, member counts, and topics. |
| `/room` | Show the current room. |
| `/create <room>` | Create a room and become its admin. |
| `/join <room>` | Join an existing room. |
| `/leave` | Leave the current room and return to `#lobby`. |
| `/who` | List online users in the current room. |
| `/me <action>` | Broadcast an action message in the current room. |
| `/topic [text]` | View the topic, or set it if you are the room admin. |
| `/kick <user>` | Admin only: remove a user from the current room. |
| `/close` | Admin only: close the current room and move members to `#lobby`. |
| `/clear` | Clear the local terminal view. |
| `/quit` | Disconnect cleanly. |

`/exit` and `/q` are accepted by the client as aliases for `/quit`.

## Deploy the main server on Fly.io

This repo includes a `Dockerfile` and `fly.toml` for Fly.io. The default config
runs `DECEN/server.py` on port `8080` and stores user data in `/data`.

1. Install and sign in to the Fly CLI.
2. Pick a unique Fly app name and edit `fly.toml`:

   ```toml
   app = "your-decen-app"
   ```

3. Create the app and a persistent volume:

   ```bash
   fly apps create your-decen-app
   fly volumes create decen_data --size 1 --region iad --app your-decen-app
   ```

4. Deploy:

   ```bash
   fly deploy --app your-decen-app
   ```

5. Connect clients to the hosted server:

   ```bash
   python DECEN/main.py --url wss://your-decen-app.fly.dev
   ```

## Data files

By default, the server reads and writes `users.json` in the same directory as
`server.py`. Use `--data-dir` to keep test, development, or production data in a
separate location. The Fly.io config uses `/data` so credentials survive app
restarts when a Fly volume is attached.

> Note: DECEN now hashes stored passwords, but local websocket traffic is still
> plain `ws://`. Fly.io terminates TLS for `wss://your-app.fly.dev` clients.
