# DECEN

DECEN is a lightweight terminal-based websocket chat application. It includes a
server (`server.py`) and a client (`main.py`) that can be run locally for quick
private chat experiments.

## Highlights

- Friendlier terminal client with `--host`, `--port`, `--username`, and
  `--no-animation` options.
- Masked password entry with `getpass`.
- Server-side commands: `/help`, `/who`, `/me <action>`, `/clear`, and `/quit`.
- Join/leave system messages and recent message history for new connections.
- Safer account storage using PBKDF2 password hashes. Older plaintext demo
  users are migrated automatically after a successful login.
- Configurable server host, port, data directory, and log level.

## Requirements

- Python 3.10+
- [`websockets`](https://websockets.readthedocs.io/)

Install the only runtime dependency:

```bash
python -m pip install -r DECEN/requirements.txt
```

## Quick start

Start the server in one terminal:

```bash
python DECEN/server.py
```

Connect with the client in another terminal:

```bash
python DECEN/main.py
```

For faster startup or screen reader usage, skip the animated intro:

```bash
python DECEN/main.py --no-animation
```

## Useful options

Server:

```bash
python DECEN/server.py --host 0.0.0.0 --port 8765 --data-dir DECEN --log-level INFO
```

Client:

```bash
python DECEN/main.py --host localhost --port 8765 --username alice
```

## Chat commands

| Command | Description |
| --- | --- |
| `/help` | Show available server commands. |
| `/who` | List online users. |
| `/me <action>` | Broadcast an action message. |
| `/clear` | Clear the local terminal view. |
| `/quit` | Disconnect cleanly. |

`/exit` and `/q` are accepted by the client as aliases for `/quit`.

## Data files

By default, the server reads and writes `users.json` in the same directory as
`server.py`. Use `--data-dir` to keep test, development, or production data in a
separate location.

> Note: DECEN now hashes stored passwords, but websocket traffic is still plain
> `ws://` unless you run it behind TLS or extend the server to use secure
> websocket certificates.
