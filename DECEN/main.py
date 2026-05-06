import asyncio as AS
import websockets as WS
import time as T


login_status = False
current_user = None


# =========================
# CLIENT CONNECTION
# =========================
async def connect_to_server():
    global login_status, current_user

    uri = "ws://localhost:8765"

    async with WS.connect(uri) as websocket:
        print("Connected to DECEN Server.")

        # =========================
        # SERVER HANDSHAKE
        # =========================
        prompt = await websocket.recv()
        username = input(prompt)
        await websocket.send(username)

        prompt = await websocket.recv()
        password = input(prompt)
        await websocket.send(password)

        response = await websocket.recv()
        print(response)

        if "AUTH FAILED" in response:
            return

        login_status = True
        current_user = username

        # =========================
        # CHAT SYSTEM
        # =========================
        async def receive():
            while True:
                try:
                    msg = await websocket.recv()
                    print(f"\n{msg}")
                except:
                    print("Disconnected from server.")
                    break

        async def send():
            while True:
                msg = await AS.to_thread(input)
                await websocket.send(msg)

        await AS.gather(receive(), send())


# =========================
# BOOT SCREEN
# =========================
async def main():
    intro = "Welcome To D.E.C.E.N."
    subtitle = "The Decentralized Encrypted Comms Network"

    for c in intro:
        print(c, end='', flush=True)
        T.sleep(0.05)

    print("\n")

    for c in subtitle:
        print(c, end='', flush=True)
        T.sleep(0.03)

    print("\n\nNetwork Status: .....Online\n")

    print("Please Log In To Access DECEN.\n")

    await connect_to_server()


# =========================
# RUN
# =========================
AS.run(main())