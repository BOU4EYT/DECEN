"""DECEN terminal client."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import time
from contextlib import suppress
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, InvalidURI, InvalidHandshake

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765


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
    print("Tip: type /help after login to see available commands.\n")


def client_help() -> str:
    return (
        "Local shortcuts: /quit exits, Ctrl+C cancels, and blank messages are ignored.\n"
        "Server commands: /help, /who, /me <action>, /clear."
    )


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
    uri = f"ws://{args.host}:{args.port}"

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
        print(f"Could not connect to {uri}. Is the DECEN server running?")
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
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host/IP.")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Server port.")
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
