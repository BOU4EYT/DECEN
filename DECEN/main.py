"""DECEN terminal client."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
import time
from contextlib import suppress
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765
DEFAULT_MAIN_SERVER = os.environ.get("DECEN_MAIN_SERVER", "wss://decen-main.fly.dev")


# =========================
# DISPLAY HELPERS
# =========================
def type_line(text: str, delay: float = 0.02) -> None:
    for character in text:
        print(character, end="", flush=True)
        time.sleep(delay)
    print()


def show_boot_screen(animated: bool) -> None:
    intro = "Welcome to D.E.C.E.N."
    subtitle = "The Decentralized Encrypted Comms Network"

    if animated:
        type_line(intro, 0.035)
        type_line(subtitle, 0.018)
    else:
        print(intro)
        print(subtitle)

    print("\nNetwork Status: Online")
    print("Tip: choose a server, then type /help after login for chatroom commands.\n")


def client_help() -> str:
    return (
        "Local shortcuts: /quit exits, /exit and /q also quit, Ctrl+C cancels, "
        "and blank messages are ignored.\n"
        "Rooms: /rooms, /create <room>, /join <room>, /leave, /who.\n"
        "Room admins: /topic <text>, /kick <user>, /close."
    )


def prompt_server_choice() -> str:
    print("Choose a DECEN server:")
    print("  1) Main DECEN server")
    print("  2) Local server on this machine")
    print("  3) Custom/self-hosted server URL")

    while True:
        choice = input("Server [1/2/3]: ").strip()
        if choice in {"", "1"}:
            return "main"
        if choice == "2":
            return "local"
        if choice == "3":
            return "custom"
        print("Please choose 1, 2, or 3.")


def build_server_uri(args: argparse.Namespace) -> str:
    if args.url:
        return normalize_websocket_uri(args.url)

    server_choice = args.server or prompt_server_choice()
    if server_choice == "main":
        return normalize_websocket_uri(args.main_url)
    if server_choice == "custom":
        custom_url = input("Websocket URL (ws:// or wss://): ").strip()
        return normalize_websocket_uri(custom_url)
    return f"ws://{args.host}:{args.port}"


def normalize_websocket_uri(uri: str) -> str:
    uri = uri.strip()
    if not uri:
        raise ValueError("Server URL cannot be empty.")
    if uri.startswith(("ws://", "wss://")):
        return uri
    return f"wss://{uri}"


# =========================
# CLIENT CONNECTION
# =========================
async def prompt_for_login(default_username: str | None) -> tuple[str, str]:
    username_prompt = "Username"
    if default_username:
        username_prompt += f" [{default_username}]"
    username_prompt += ": "

    username = await asyncio.to_thread(input, username_prompt)
    username = username.strip() or (default_username or "")
    password = await asyncio.to_thread(getpass.getpass, "Password: ")
    return username, password


async def receive_messages(websocket: Any) -> None:
    async for message in websocket:
        if message.startswith("\033c"):
            print("\033c", end="")
            message = message.removeprefix("\033c")
        print(f"\n{message}\n> ", end="", flush=True)


async def send_messages(websocket: Any) -> None:
    print("> ", end="", flush=True)
    while True:
        message = await asyncio.to_thread(input)
        message = message.strip()
        if not message:
            print("> ", end="", flush=True)
            continue
        if message.lower() in {"/exit", "/q"}:
            message = "/quit"
        await websocket.send(message)
        if message.lower() == "/quit":
            return
        print("> ", end="", flush=True)


async def connect_to_server(args: argparse.Namespace) -> int:
    try:
        uri = build_server_uri(args)
    except ValueError as error:
        print(f"Invalid server selection: {error}")
        return 1

    try:
        async with websockets.connect(
            uri, ping_interval=20, ping_timeout=20
        ) as websocket:
            print(f"Connected to DECEN server at {uri}.")

            username, password = await prompt_for_login(args.username)

            prompt = await websocket.recv()
            if prompt != "USERNAME:":
                print(f"Unexpected server prompt: {prompt}")
                return 1
            await websocket.send(username)

            prompt = await websocket.recv()
            if prompt != "PASSWORD:":
                print(f"Unexpected server prompt: {prompt}")
                return 1
            await websocket.send(password)

            response = await websocket.recv()
            print(response)
            if response.startswith("AUTH FAILED"):
                return 1

            print(client_help())
            receive_task = asyncio.create_task(receive_messages(websocket))
            send_task = asyncio.create_task(send_messages(websocket))

            done, pending = await asyncio.wait(
                {receive_task, send_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                task.result()

    except (ConnectionRefusedError, OSError):
        print(f"Could not connect to {uri}. Is that DECEN server running?")
        return 1
    except (InvalidURI, InvalidHandshake) as error:
        print(f"Unable to open websocket connection: {error}")
        return 1
    except ConnectionClosed:
        print("Disconnected from DECEN server.")
    except KeyboardInterrupt:
        print("\nGoodbye.")

    return 0


# =========================
# CLI
# =========================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Connect to a DECEN chat server.")
    parser.add_argument(
        "--server",
        choices=("main", "local", "custom"),
        help="Server profile to use. Omit this to choose interactively.",
    )
    parser.add_argument(
        "--url",
        help="Direct websocket URL for any DECEN server, e.g. wss://example.fly.dev.",
    )
    parser.add_argument(
        "--main-url",
        default=DEFAULT_MAIN_SERVER,
        help="Main DECEN server URL used by --server main.",
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help="Local/custom server host/IP."
    )
    parser.add_argument(
        "--port", default=DEFAULT_PORT, type=int, help="Local/custom server port."
    )
    parser.add_argument("--username", help="Pre-fill the login username prompt.")
    parser.add_argument(
        "--no-animation",
        action="store_true",
        help="Skip the boot animation for faster startup and screen readers.",
    )
    return parser


async def main() -> int:
    args = build_parser().parse_args()
    show_boot_screen(animated=not args.no_animation)
    return await connect_to_server(args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
