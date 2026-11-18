"""Reticulum link to a RetiBBS server.

Runs on Reticulum's threads and never touches Tk. Everything the GUI
needs to know is put on self.events, which the GUI drains on a timer
(the same pattern partyline uses).

RetiBBS is menu based: the server keeps track of which area each user
is in (Main Menu, Message Boards, Chat) and the same command means
different things in each. goto() and run() send the commands needed to
move between areas and wait for the server's CTRL AREA / CTRL BOARD
reply before sending the next one.
"""

import json
import queue
import threading
import time
from collections import deque

import RNS

from .parse import classify

APP_NAME = "retibbs"
ASPECT = "bbs"
MAIN, BOARDS, CHAT = "Main Menu", "Message Boards", "Chat"
PING_SECONDS = 30
STEP_TIMEOUT = 25
PATH_TIMEOUT = 30


class Discovery:
    """Collects RetiBBS server announces."""

    aspect_filter = f"{APP_NAME}.{ASPECT}"

    def __init__(self):
        self.servers = {}
        self.lock = threading.Lock()

    def received_announce(self, destination_hash, announced_identity, app_data):
        name = None
        if app_data:
            try:
                name = json.loads(app_data.decode("utf-8")).get("server_name")
            except (ValueError, UnicodeDecodeError, AttributeError):
                pass
        with self.lock:
            self.servers[destination_hash.hex()] = {
                "name": name or RNS.prettyhexrep(destination_hash),
                "seen": time.time(),
                "hops": RNS.Transport.hops_to(destination_hash),
            }

    def snapshot(self):
        with self.lock:
            return dict(self.servers)


class Client:
    def __init__(self, identity):
        self.identity = identity
        self.events = queue.Queue()
        self.link = None
        self.server_hash = None
        self.area = None
        self.board = None
        self.room = None
        self.user_name = None
        self.is_admin = False
        self.alert_address = None  # None until the server tells us; "" if not set
        self.rtt = None
        self._ping_sent = 0.0
        self._steps = deque()
        self._waiting = None  # (kind, value, deadline)
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._expect_welcome = False

    # connection
    def event(self, *event):
        self.events.put(event)

    @property
    def connected(self):
        return self.link is not None and self.link.status == RNS.Link.ACTIVE

    def connect(self, hash_hex):
        self.server_hash = hash_hex
        threading.Thread(target=self._connect, args=(hash_hex,), daemon=True).start()

    def _connect(self, hash_hex):
        try:
            destination_hash = bytes.fromhex(hash_hex)
            if len(destination_hash) != RNS.Reticulum.TRUNCATED_HASHLENGTH // 8:
                raise ValueError
        except ValueError:
            self.event("failed", f"Not a valid destination hash: {hash_hex}")
            return
        if not RNS.Transport.has_path(destination_hash):
            self.event("status", "Requesting path...")
            RNS.Transport.request_path(destination_hash)
            deadline = time.time() + PATH_TIMEOUT
            while not RNS.Transport.has_path(destination_hash):
                if time.time() > deadline or self._stopped.is_set():
                    self.event("failed", "No path to the server. Is it announcing, and on a network you can reach?")
                    return
                time.sleep(0.2)
        server_identity = RNS.Identity.recall(destination_hash)
        if server_identity is None:
            self.event("failed", "Could not recall the server identity.")
            return
        destination = RNS.Destination(server_identity, RNS.Destination.OUT, RNS.Destination.SINGLE, APP_NAME, ASPECT)
        self.event("status", "Establishing link...")
        link = RNS.Link(destination, established_callback=self._established, closed_callback=self._closed)
        link.set_packet_callback(self._packet)
        link.set_resource_strategy(RNS.Link.ACCEPT_APP)
        link.set_resource_callback(lambda advertisement: True)
        link.set_resource_concluded_callback(self._resource)
        self.link = link

    def _established(self, link):
        # the server's first resource after connecting is its welcome message (the theme's welcome_message.txt)
        self._expect_welcome = True
        link.identify(self.identity)
        self.event("connected", RNS.Transport.hops_to(link.destination.hash))
        threading.Thread(target=self._housekeeping, args=(link,), daemon=True).start()

    def _closed(self, link):
        if link is not self.link:
            return
        reasons = {RNS.Link.TIMEOUT: "timed out", RNS.Link.DESTINATION_CLOSED: "closed by the server"}
        self.link = None
        self.area = self.board = self.room = None
        with self._lock:
            self._steps.clear()
            self._waiting = None
        self.event("disconnected", reasons.get(link.teardown_reason, "closed"))

    def disconnect(self):
        self._stopped.set()
        link = self.link
        if link is not None:
            link.teardown()

    def _housekeeping(self, link):
        last_ping = 0.0
        while link.status == RNS.Link.ACTIVE and not self._stopped.is_set():
            now = time.time()
            if now - last_ping > PING_SECONDS:
                last_ping = now
                self._ping_sent = now
                self._raw(b"PING")
            with self._lock:
                if self._waiting and now > self._waiting[2]:
                    self.event("error", f"The server did not confirm '{self._waiting[1]}'. Continuing anyway.")
                    self._waiting = None
            self._pump()
            time.sleep(0.5)

    # sending
    def _raw(self, data):
        link = self.link
        if link is None or link.status != RNS.Link.ACTIVE:
            return False
        if len(data) > link.mdu:
            self.event("error", f"That is {len(data)} bytes; RetiBBS commands must fit in one packet ({link.mdu} bytes).")
            return False
        try:
            RNS.Packet(link, data).send()
            return True
        except Exception as error:
            self.event("error", f"Send failed: {error}")
            return False

    def fits(self, command):
        link = self.link
        return link is None or len(command.encode("utf-8")) <= link.mdu

    @property
    def packet_limit(self):
        """Bytes in one packet on this link: the size limit for every command, post and reply."""
        return self.link.mdu if self.link else None

    def chat_limit(self):
        """Bytes left for a chat message.

        The server sends each chat line to the others as one packet, "[room] Name: text", with "[" escaped, so the
        room and name use up part of the packet.
        """
        if self.link is None:
            return None
        name = max(len((self.user_name or "").encode("utf-8")), len("(You)"))
        return self.link.mdu - len(f"[{self.room or ''}] : ".encode("utf-8")) - name - 8

    @staticmethod
    def chat_cost(text):
        return len(text.encode("utf-8")) + 2 * text.count("[")

    def planned_area(self):
        with self._lock:
            for kind, _cmd, expect in reversed(self._steps):
                if kind == "area":
                    return expect
            if self._waiting and self._waiting[0] == "area":
                return self._waiting[1]
            return self.area

    def run(self, *steps):
        """Queue commands. A step is a string, or (command, kind, expected) to wait for a CTRL reply."""
        with self._lock:
            for step in steps:
                if isinstance(step, str):
                    step = (step, None, None)
                command, kind, expected = step
                self._steps.append((kind, command, expected))
        self._pump()

    def goto(self, target, *then):
        """Move to an area, then run the given commands."""
        current = self.planned_area()
        steps = []
        if current != target:
            if current == BOARDS:
                steps.append(("b", "area", MAIN))
            elif current == CHAT:
                steps.append(("/b", "area", MAIN))
            if target == BOARDS:
                steps.append(("b", "area", BOARDS))
            elif target == CHAT:
                steps.append(("c", "area", CHAT))
        self.run(*steps, *then)

    def _pump(self):
        while True:
            with self._lock:
                if self._waiting or not self._steps or not self.connected or self.area is None:
                    return
                kind, command, expected = self._steps.popleft()
                if kind == "area" and self.area == expected:
                    continue
                if kind == "board" and self.board == expected:
                    continue
                if kind:
                    self._waiting = (kind, expected, time.time() + STEP_TIMEOUT)
            self._raw(command.encode("utf-8"))

    def _satisfy(self, kind, value):
        with self._lock:
            if self._waiting and self._waiting[0] == kind and self._waiting[1] == value:
                self._waiting = None
        self._pump()

    # receiving
    def _resource(self, resource):
        if resource.status == RNS.Resource.COMPLETE:
            data = resource.data.read()
            if self._expect_welcome:
                self._expect_welcome = False
                self.event("welcome", data.decode("utf-8", "replace"))
            self._text(data)

    def _packet(self, data, packet):
        if data == b"PONG":
            self.rtt = time.time() - self._ping_sent
            self.event("rtt", self.rtt)
            return
        if data.startswith(b"CTRL "):
            self._control(data.decode("utf-8", "replace"))
            return
        self._text(data)

    def _control(self, text):
        parts = text.split(" ", 2)
        kind = parts[1] if len(parts) > 1 else ""
        value = parts[2].strip() if len(parts) > 2 else ""
        if value == "None":
            value = None
        if kind == "CLS":
            self.event("cls")
            return
        if kind == "AREA":
            self.area = value
            if value == MAIN:
                self.board = None
            if value != CHAT and self.room:
                self.event("left", self.room)
                self.room = None
            self.event("area", value)
            self._satisfy("area", value)
        elif kind == "BOARD":
            self.board = value
            self.event("board", value)
            self._satisfy("board", value)
        elif kind == "ROOM":
            if self.room and value != self.room:
                self.event("left", self.room)
            self.room = value
            self.event("room", value)

    def _text(self, data):
        text = data.decode("utf-8", "replace")
        for event in classify(text, self.area, self.room):
            if event[0] == "joined":
                self.room = event[1]
            elif event[0] == "left":
                self.room = None
            elif event[0] == "hello":
                self.user_name, self.is_admin, self.alert_address = event[1], event[2], event[3]
            self.events.put(event)
