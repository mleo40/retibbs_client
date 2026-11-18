"""Tk desktop client for RetiBBS with partyline's look and layout.

Layout: the toolbar only handles the connection. The tree on the right lists boards, messages, chat rooms and (for
admins) users. The tabs on the left are the three things you can look at, each with its own buttons in its header:
Chat (the room you are in), Message (the post you opened) and Server log (raw server text and typed commands).
"""

import argparse
import os
import platform
import queue
import re
import time
import tkinter as tk
import webbrowser
from importlib import metadata
from tkinter import messagebox, ttk
from tkinter import font as tkfont

import RNS

from . import __version__, prefs
from .client import BOARDS, CHAT, MAIN, Client, Discovery
from .parse import styled_runs
from .theme import PALETTES, apply_theme

APP_TITLE = "RetiBBS"
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
REFRESH_MS = 100
NOTICE_MS = 9000
ROOT_ID, BOARDS_ID, ROOMS_ID, USERS_ID, OFFLINE_ID = "server", "boards", "rooms", "users", "offline"
CHAT_TAB, MESSAGE_TAB, LOG_TAB = 0, 1, 2
MOTD_BOARD = "motd"  # the newest post on a board with this name is the message of the day
BOARD_NAME = re.compile(r"[A-Za-z0-9]{3,20}")
LXMF_ADDRESS = re.compile(r"[0-9a-f]{32}")
NAME_TAKEN = re.compile(r"^ERROR: The name '.*' is already taken\.$")
REPO_URL = "https://github.com/mleo40/retibbs_client"
CREDITS = (
    ("RetiBBS", "Steve Miller, KC1AWV", "MIT", "https://github.com/kc1awv/RetiBBS",
     "The BBS server and protocol this client talks to"),
    ("partyline", "RFnexus", "Public domain", "https://github.com/RFnexus/partyline",
     "Look and layout: theme, palettes, window arrangement"),
    ("Reticulum", "Mark Qvist", "Reticulum License", "https://reticulum.network",
     "The network stack"),
    ("Rich", "Will McGugan", "MIT", "https://github.com/Textualize/rich",
     "Colors in server text"),
    ("Tabler Icons", "Tabler", "MIT", "https://tabler.io/icons",
     "Icons"),
)

CHAT_LIMIT_TEXT = "Live chat is not saved. Message boards are."
POST_LIMIT_TEXT = (
    "Each post or reply must fit in one Reticulum packet, topic included: a few hundred bytes over LoRa or packet "
    "radio, far more over TCP. Longer text is refused. "
    "Posts cannot be edited or deleted after sending, and files cannot be attached."
)
ALERT_LIMIT_TEXT = (
    "The server sends alerts as LXMF messages to another app, such as Sideband, Columba, MeshChat or NomadNet; "
    "this client cannot receive them. The server cannot remove an address, only replace it. To stop alerts, "
    "turn them off board by board."
)


def load_icon(name):
    try:
        return tk.PhotoImage(file=os.path.join(ICON_DIR, name + ".png"))
    except tk.TclError:
        return tk.PhotoImage(width=1, height=1)


def identity_path():
    # the same file the RetiBBS Textual client uses, so you keep your BBS account
    return os.path.join(RNS.Reticulum.storagepath, "retibbs_client_identity")


def load_identity():
    path = identity_path()
    if os.path.isfile(path):
        identity = RNS.Identity.from_file(path)
        if identity is not None:
            return identity
    identity = RNS.Identity()
    identity.to_file(path)
    return identity


def clean_hash(text):
    return text.strip().strip("<>").replace(":", "").lower()


def limit_note(parent, text):
    """A server limit, shown the same way everywhere: a tinted strip starting with "Server limit"."""
    frame = ttk.Frame(parent, style="Limit.TFrame", padding=(8, 4))
    label = ttk.Label(frame, text="ⓘ  Server limit: " + text, style="Limit.TLabel", justify="left")
    label.pack(fill="x")
    frame.bind("<Configure>", lambda event: label.configure(wraplength=max(200, event.width - 20)))
    return frame


# dialogs
class Dialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda event: self.cancel())
        self.body = ttk.Frame(self, padding=10)
        self.body.pack(fill="both", expand=True)

    def buttons(self, ok_text="OK"):
        row = ttk.Frame(self.body)
        row.grid(row=99, column=0, columnspan=3, sticky="e", pady=(10, 0))
        self.ok_button = ttk.Button(row, text=ok_text, command=self.ok)
        self.ok_button.pack(side="right")
        ttk.Button(row, text="Cancel", command=self.cancel).pack(side="right", padx=(0, 4))

    def show(self):
        self.update_idletasks()
        self.geometry(f"+{self.master.winfo_rootx() + 60}+{self.master.winfo_rooty() + 60}")
        self.grab_set()
        self.wait_window()
        return self.result

    def ok(self):
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


class ConnectDialog(Dialog):
    def __init__(self, app):
        super().__init__(app.root, "Connect to a BBS")
        self.app = app
        body = self.body
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(body)
        self.notebook.grid(row=0, column=0, columnspan=3, sticky="nsew")

        self.saved = self.make_tree(("name", "hash"), ("Name", "Address"))
        self.discovered = self.make_tree(
            ("name", "hash", "hops", "seen"), ("Announced name", "Address", "Hops", "Last seen")
        )
        self.notebook.add(self.saved.master, text="My BBS list")
        self.notebook.add(self.discovered.master, text="Heard on the network")

        ttk.Label(body, text="Name").grid(row=1, column=0, sticky="w", pady=(10, 2))
        self.name_var = tk.StringVar()
        ttk.Entry(body, textvariable=self.name_var).grid(row=1, column=1, sticky="ew", padx=4, pady=(10, 2))
        ttk.Label(body, text="Address").grid(row=2, column=0, sticky="w", pady=2)
        self.hash_var = tk.StringVar()
        entry = ttk.Entry(body, textvariable=self.hash_var, width=36)
        entry.grid(row=2, column=1, sticky="ew", padx=4, pady=2)
        entry.bind("<Return>", lambda event: self.ok())
        side = ttk.Frame(body)
        side.grid(row=1, column=2, rowspan=2, sticky="n", pady=(10, 0))
        ttk.Button(side, text="Save to my list", command=self.save).pack(fill="x")
        ttk.Button(side, text="Remove", command=self.remove).pack(fill="x", pady=(4, 0))
        ttk.Label(
            body, style="Muted.TLabel", wraplength=520, justify="left",
            text="Name is how the BBS shows in your list and window. Leave it empty to use the name the server "
                 "announces. Connecting saves the BBS to your list.",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.buttons("Connect")
        self.fill_saved()
        self.tick()
        if not self.app.servers:
            self.notebook.select(1)
        self.geometry("660x430")

    def make_tree(self, columns, headings):
        frame = ttk.Frame(self.notebook)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
            tree.column(column, width=60 if column == "hops" else 170, stretch=column != "hops")
        tree.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(frame, command=tree.yview).pack(side="right", fill="y")
        tree.bind("<<TreeviewSelect>>", lambda event: self.picked(tree))
        tree.bind("<Double-1>", lambda event: self.ok())
        return tree

    def picked(self, tree):
        selection = tree.selection()
        if selection:
            hash_hex = selection[0]
            self.hash_var.set(hash_hex)
            saved = self.app.servers.get(hash_hex, {})
            self.name_var.set(saved.get("name", "") if saved.get("custom") else "")

    def fill_saved(self):
        self.saved.delete(*self.saved.get_children())
        for hash_hex, entry in sorted(self.app.servers.items(), key=lambda item: item[1].get("name", "").lower()):
            self.saved.insert("", "end", iid=hash_hex, values=(entry.get("name", ""), hash_hex))

    def tick(self):
        if not self.winfo_exists():
            return
        selected = self.discovered.selection()
        self.discovered.delete(*self.discovered.get_children())
        for hash_hex, info in sorted(self.app.discovery.snapshot().items(), key=lambda item: -item[1]["seen"]):
            seen = time.strftime("%H:%M:%S", time.localtime(info["seen"]))
            hops = "" if info["hops"] in (None, RNS.Transport.PATHFINDER_M) else info["hops"]
            self.discovered.insert("", "end", iid=hash_hex, values=(info["name"], hash_hex, hops, seen))
        if selected and self.discovered.exists(selected[0]):
            self.discovered.selection_set(selected[0])
        self.after(2000, self.tick)

    def checked_hash(self, title):
        hash_hex = clean_hash(self.hash_var.get())
        if len(hash_hex) != 32:
            messagebox.showerror(title, "Enter or pick a 32 character address.", parent=self)
            return None
        return hash_hex

    def save(self):
        hash_hex = self.checked_hash("Save")
        if hash_hex:
            self.app.remember_server(hash_hex, self.name_var.get().strip())
            self.fill_saved()
            self.notebook.select(0)
            self.saved.selection_set(hash_hex)

    def remove(self):
        selection = self.saved.selection()
        if selection:
            self.app.servers.pop(selection[0], None)
            self.app.servers.save()
            self.fill_saved()

    def ok(self):
        hash_hex = self.checked_hash("Connect")
        if hash_hex:
            self.app.remember_server(hash_hex, self.name_var.get().strip())
            self.result = hash_hex
            self.destroy()


class PostDialog(Dialog):
    def __init__(self, app, boards, board=None, reply_to=None):
        title = f"Reply to {reply_to['author']}" if reply_to else "New post"
        super().__init__(app.root, title)
        self.app = app
        self.reply_to = reply_to
        body = self.body
        body.columnconfigure(1, weight=1)
        body.rowconfigure(3, weight=1)
        limit_note(body, POST_LIMIT_TEXT).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        if reply_to:
            ttk.Label(body, text=f"Re: {reply_to['topic']}  ({reply_to['board']})", font=app.bold_font).grid(
                row=1, column=0, columnspan=2, sticky="w"
            )
        else:
            ttk.Label(body, text="Board").grid(row=1, column=0, sticky="w")
            self.board = ttk.Combobox(body, values=boards, state="readonly")
            self.board.grid(row=1, column=1, sticky="ew", pady=2)
            if board in boards:
                self.board.set(board)
            elif boards:
                self.board.set(boards[0])
            ttk.Label(body, text="Topic").grid(row=2, column=0, sticky="w")
            self.topic = ttk.Entry(body)
            self.topic.grid(row=2, column=1, sticky="ew", pady=2)
            self.topic.bind("<KeyRelease>", lambda event: self.update_count())
            self.topic.focus_set()
        self.text = tk.Text(body, width=64, height=10, wrap="word", font=app.text_font)
        self.text.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        apply_theme(app.root, app.palette, texts=[self.text])
        self.count = ttk.Label(body)
        self.count.grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.text.bind("<KeyRelease>", lambda event: self.update_count())
        if reply_to:
            self.text.focus_set()
        self.buttons("Send")
        self.update_count()

    def command(self):
        content = self.text.get("1.0", "end").strip()
        if self.reply_to:
            return f"re {self.reply_to['id']} | {content}", content
        topic = self.topic.get().strip()
        return f"p {topic} | {content}", content

    def update_count(self):
        command, _ = self.command()
        limit = self.app.client.packet_limit if self.app.client else None
        used = len(command.encode("utf-8"))
        if limit is None:
            self.count.configure(text=f"{used} bytes", style="Muted.TLabel")
            return
        over = used > limit
        text = f"{used} of {limit} bytes used" + (f", {used - limit} too many" if over else f", {limit - used} left")
        self.count.configure(text=text, style="Over.TLabel" if over else "Muted.TLabel")
        self.ok_button.state(["disabled" if over else "!disabled"])

    def ok(self):
        command, content = self.command()
        if not content:
            messagebox.showerror(self.title(), "Write something first.", parent=self)
            return
        if not self.reply_to:
            topic = self.topic.get().strip()
            if not self.board.get() or not topic:
                messagebox.showerror(self.title(), "Pick a board and enter a topic.", parent=self)
                return
            if "|" in topic:
                messagebox.showerror(self.title(), "The topic cannot contain '|'.", parent=self)
                return
        if not self.app.client.fits(command):
            messagebox.showerror(self.title(), "Too long to fit in one packet. Shorten it and try again.", parent=self)
            return
        self.result = (self.reply_to["board"] if self.reply_to else self.board.get(), command)
        self.destroy()


class SettingsDialog(Dialog):
    def __init__(self, app):
        super().__init__(app.root, "Settings")
        self.app = app
        body = self.body
        body.columnconfigure(0, weight=1)

        profile = ttk.LabelFrame(body, text="Profile", padding=8)
        profile.grid(row=0, column=0, sticky="ew")
        profile.columnconfigure(1, weight=1)
        ttk.Label(profile, text="Display name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=app.settings["display_name"])
        ttk.Entry(profile, textvariable=self.name_var, width=32).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(
            profile, style="Muted.TLabel", wraplength=440, justify="left",
            text="Sent to every BBS you connect to. Each BBS allows a name only once.",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        alerts = ttk.LabelFrame(body, text="Board alerts", padding=8)
        alerts.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        alerts.columnconfigure(1, weight=1)
        ttk.Label(alerts, text="LXMF address").grid(row=0, column=0, sticky="w")
        self.alert_var = tk.StringVar(value=app.settings["alert_address"])
        ttk.Entry(alerts, textvariable=self.alert_var, width=34).grid(row=0, column=1, sticky="ew", padx=(8, 4))
        self.test_button = ttk.Button(alerts, text="Send test", command=self.test)
        self.test_button.grid(row=0, column=2)
        if not (app.client and app.client.connected):
            self.test_button.state(["disabled"])
        ttk.Label(
            alerts, style="Muted.TLabel", wraplength=440, justify="left",
            text="Where the BBS tells you about new posts on boards you watch, and replies to your posts. Turn alerts "
                 "on per board: right click a board.",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 6))
        limit_note(alerts, ALERT_LIMIT_TEXT).grid(row=2, column=0, columnspan=3, sticky="ew")

        looks = ttk.LabelFrame(body, text="Appearance", padding=8)
        looks.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(looks, text="Font size").grid(row=0, column=0, sticky="w")
        self.size_var = tk.IntVar(value=app.settings["font_size"])
        ttk.Spinbox(looks, from_=8, to=20, textvariable=self.size_var, width=5).grid(row=0, column=1, sticky="w", padx=8)
        self.dark_var = tk.BooleanVar(value=app.settings["theme"] == "dark")
        ttk.Checkbutton(looks, text="Dark mode", variable=self.dark_var).grid(row=0, column=2, sticky="w", padx=(12, 0))

        who = ttk.LabelFrame(body, text="Your BBS identity", padding=8)
        who.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(who, text=app.identity.hash.hex()).pack(side="left")
        ttk.Button(who, text="Copy", command=lambda: app.copy(app.identity.hash.hex())).pack(side="right")
        self.buttons()

    def address(self):
        address = clean_hash(self.alert_var.get())
        if address and not LXMF_ADDRESS.fullmatch(address):
            messagebox.showerror("Settings", "An LXMF address is 32 characters, 0-9 and a-f.", parent=self)
            return None
        return address

    def test(self):
        address = self.address()
        if address is None:
            return
        if not address:
            messagebox.showerror("Settings", "Enter your LXMF address first.", parent=self)
            return
        self.app.send_alert_test(address)

    def ok(self):
        address = self.address()
        if address is None:
            return
        settings = self.app.settings
        new_name = self.name_var.get().strip()
        commands = []
        if new_name and new_name != settings["display_name"]:
            commands.append(f"n {new_name}")
        client = self.app.client
        if address and (address != settings["alert_address"] or (client and client.alert_address != address)):
            commands.append(f"d {address}")
        settings["display_name"] = new_name
        settings["alert_address"] = address
        try:
            settings["font_size"] = max(8, min(20, int(self.size_var.get())))
        except (tk.TclError, ValueError):
            pass
        settings["theme"] = "dark" if self.dark_var.get() else "light"
        settings.save()
        self.app.dark_var.set(settings["theme"] == "dark")
        self.app.apply_settings()
        self.destroy()
        if commands and client and client.connected:
            self.app.navigate(MAIN, *commands, "h")


class AboutDialog(Dialog):
    def __init__(self, app):
        super().__init__(app.root, "About")
        body = self.body
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="RetiBBS desktop client", font=app.title_font).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text=f"Version {__version__}").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(
            body, wraplength=520, justify="left",
            text="A desktop client for RetiBBS bulletin boards on Reticulum networks: boards, chat rooms, board "
                 "alerts and admin tools, with the server's limits shown where they apply.",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.link(body, REPO_URL, row=3)
        ttk.Label(body, text="MIT License, Copyright (c) 2026 mleo40", style="Muted.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w"
        )

        ttk.Label(body, text="Built on", font=app.bold_font).grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 2))
        row = 6
        for name, author, licence, url, what in CREDITS:
            ttk.Label(body, text=name, font=app.bold_font).grid(row=row, column=0, sticky="nw", padx=(0, 12))
            ttk.Label(body, text=f"{what}. By {author}, {licence}.", wraplength=420, justify="left").grid(
                row=row, column=1, sticky="w"
            )
            self.link(body, url, row=row + 1, column=1)
            row += 2

        versions = f"Python {platform.python_version()}, Reticulum {package_version('rns')}, Tk {tk.TkVersion}"
        ttk.Label(body, text=versions, style="Muted.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(12, 0))
        identity = app.identity.hash.hex()
        who = ttk.Frame(body)
        who.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Label(who, text=f"Your BBS identity: {identity}", style="Muted.TLabel").pack(side="left")
        ttk.Button(who, text="Copy", command=lambda: app.copy(identity)).pack(side="right")

        buttons = ttk.Frame(body)
        buttons.grid(row=99, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Close", command=self.ok).pack(side="right")

    @staticmethod
    def link(parent, url, row, column=0):
        label = ttk.Label(parent, text=url, foreground="#3b82c4", cursor="hand2")
        label.grid(row=row, column=column, columnspan=2 - column, sticky="w")
        label.bind("<Button-1>", lambda event: webbrowser.open(url))


def package_version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


# main window
class App:
    def __init__(self, root, identity, settings, servers, discovery):
        self.root = root
        self.identity = identity
        self.settings = settings
        self.servers = servers
        self.discovery = discovery
        self.client = None
        self.server_name = None
        self.server_hash = None
        self.reset_state()
        self.started = False
        self.quiet_alert = False
        self.notice_job = None
        self.palette = PALETTES.get(settings["theme"], PALETTES["light"])
        self.color_tags = set()

        root.title(APP_TITLE)
        root.minsize(760, 460)
        if settings["window"]:
            try:
                root.geometry(settings["window"])
            except tk.TclError:
                pass
        icon_names = ("server", "channel", "channel_locked", "user_idle", "rns_online", "rns_off")
        self.icons = {name: load_icon(name) for name in icon_names}
        # copies of the named fonts, so the families resolve to real fonts
        self.text_font = tkfont.nametofont("TkDefaultFont").copy()
        self.fixed_font = tkfont.nametofont("TkFixedFont").copy()
        self.bold_font = tkfont.nametofont("TkDefaultFont").copy()
        self.bold_font.configure(weight="bold")
        self.title_font = tkfont.nametofont("TkDefaultFont").copy()
        self.title_font.configure(weight="bold")
        self.fixed_bold_font = tkfont.nametofont("TkFixedFont").copy()
        self.fixed_bold_font.configure(weight="bold")

        self.build_menu()
        self.build_toolbar()
        self.build_notice()
        self.build_statusbar()
        self.build_body()
        self.apply_settings()
        self.set_connected_widgets(False)
        self.offline()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(REFRESH_MS, self.refresh)

    def reset_state(self):
        self.boards = []
        self.messages = {}  # board -> (page, pages, [message])
        self.unread = {}  # board -> set of ids
        self.watched = set()
        self.rooms = []
        self.users = None  # None until an admin loads them
        self.reading = None
        self.welcome = ""  # the server's welcome message, sent once on connect
        self.motd = None  # newest post on the motd board
        self.motd_state = None  # "listing", or ("reading", id) while the motd is being fetched
        self.motd_checked = False

    # building
    def build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        server_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Server", menu=server_menu)
        server_menu.add_command(label="Connect...", accelerator="Ctrl+O", command=self.connect_dialog)
        server_menu.add_command(label="Rename this BBS...", command=self.rename_server)
        server_menu.add_command(label="Disconnect", accelerator="Ctrl+D", command=self.disconnect)
        server_menu.add_separator()
        server_menu.add_command(label="Settings...", command=self.settings_dialog)
        server_menu.add_separator()
        server_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.quit)

        bbs_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="BBS", menu=bbs_menu)
        bbs_menu.add_command(label="New post...", accelerator="Ctrl+N", command=self.new_post)
        bbs_menu.add_command(label="Refresh", accelerator="F5", command=self.refresh_view)
        bbs_menu.add_separator()
        bbs_menu.add_command(label="Users (admins)", command=self.load_users)
        bbs_menu.add_command(label="Check my account", command=lambda: self.navigate(MAIN, "h", log=True))
        bbs_menu.add_command(label="Server help", command=self.server_help)

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Chat", accelerator="Ctrl+1", command=lambda: self.notebook.select(CHAT_TAB))
        view_menu.add_command(label="Message", accelerator="Ctrl+2", command=lambda: self.notebook.select(MESSAGE_TAB))
        view_menu.add_command(label="Server log", accelerator="Ctrl+3", command=lambda: self.notebook.select(LOG_TAB))
        view_menu.add_separator()
        self.dark_var = tk.BooleanVar(value=self.settings["theme"] == "dark")
        view_menu.add_checkbutton(label="Dark mode", variable=self.dark_var, command=self.toggle_theme)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Server limits", command=self.show_limits)
        help_menu.add_command(label="About", command=self.about)

        self.menus = [menubar, server_menu, bbs_menu, view_menu, help_menu]
        bindings = {
            "<Control-o>": self.connect_dialog, "<Control-d>": self.disconnect, "<Control-q>": self.quit,
            "<Control-n>": self.new_post, "<F5>": self.refresh_view,
            "<Control-Key-1>": lambda: self.notebook.select(CHAT_TAB),
            "<Control-Key-2>": lambda: self.notebook.select(MESSAGE_TAB),
            "<Control-Key-3>": lambda: self.notebook.select(LOG_TAB),
        }
        for sequence, command in bindings.items():
            self.root.bind(sequence, lambda event, command=command: command())

    def build_toolbar(self):
        """Connection only. What you can do with boards, messages and rooms is in each tab's header."""
        toolbar = ttk.Frame(self.root, padding=(6, 4))
        toolbar.pack(fill="x")
        self.toolbar = toolbar
        ttk.Button(toolbar, text="Connect...", command=self.connect_dialog).pack(side="left")
        self.disconnect_button = ttk.Button(toolbar, text="Disconnect", command=self.disconnect)
        self.disconnect_button.pack(side="left", padx=(4, 0))
        self.server_label = ttk.Label(toolbar, font=self.title_font)
        self.server_label.pack(side="left", padx=(14, 0))
        self.account_label = ttk.Label(toolbar, style="Muted.TLabel")
        self.account_label.pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Settings", command=self.settings_dialog).pack(side="right")

    def build_notice(self):
        """A strip under the toolbar for the server's answers: errors and confirmations."""
        self.notice_frame = ttk.Frame(self.root, padding=(8, 4))
        self.notice_label = ttk.Label(self.notice_frame)
        self.notice_label.pack(side="left", fill="x", expand=True)
        close = ttk.Label(self.notice_frame, text="✕", cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda event: self.hide_notice())
        self.notice_close = close

    def build_statusbar(self):
        bar = ttk.Frame(self.root, padding=(6, 2))
        bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="Not connected")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        self.rns_label = ttk.Label(bar, image=self.icons["rns_off"])
        self.rns_label.pack(side="right")
        self.rtt_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.rtt_var).pack(side="right", padx=8)
        self.alert_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.alert_var).pack(side="right", padx=8)

    def build_body(self):
        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=4, pady=2)
        self.pane = pane
        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=2)
        pane.add(right, weight=1)
        self.root.after(50, self.place_sash)

        self.notebook = ttk.Notebook(left)
        self.notebook.pack(fill="both", expand=True)
        self.build_chat_tab()
        self.build_message_tab()
        self.build_log_tab()

        tree_frame = ttk.Frame(right)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(tree_frame, command=self.tree.yview).pack(side="right", fill="y")
        ttk.Label(right, text="Double click to open. Right click for more.", style="Muted.TLabel").pack(
            anchor="w", pady=(3, 0)
        )
        self.tree.tag_configure("self", font=self.bold_font)
        self.tree.tag_configure("unread", font=self.bold_font)
        self.tree.bind("<Double-1>", self.tree_open)
        self.tree.bind("<Return>", self.tree_open)
        # Right click is Button-3 on Linux and Windows; Tk on macOS reports it as Button-2, or Ctrl-click
        right_clicks = ("<Button-3>",)
        if self.root.tk.call("tk", "windowingsystem") == "aqua":
            right_clicks = ("<Button-2>", "<Button-3>", "<Control-Button-1>")
        for sequence in right_clicks:
            self.tree.bind(sequence, self.tree_menu)

    def tab(self, title):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=title)
        header = ttk.Frame(frame, style="Header.TFrame", padding=(8, 5))
        header.pack(fill="x")
        return frame, header

    def text_area(self, frame):
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True, pady=(3, 0))
        text = tk.Text(holder, wrap="word", state="disabled", height=10, padx=6, pady=4)
        scroll = ttk.Scrollbar(holder, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        return text

    def entry_row(self, frame, send):
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(3, 0))
        entry = ttk.Entry(row)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda event: send())
        button = ttk.Button(row, text="Send", command=send)
        button.pack(side="right", padx=(3, 0))
        return row, entry, button

    def build_chat_tab(self):
        frame, header = self.tab("Chat")
        self.room_label = ttk.Label(header, style="Header.TLabel", font=self.bold_font)
        self.room_label.pack(side="left")
        self.room_hint = ttk.Label(header, style="HeaderMuted.TLabel")
        self.room_hint.pack(side="left", padx=(8, 0))
        self.leave_button = ttk.Button(header, text="Leave room", command=self.leave_room)
        self.leave_button.pack(side="right")
        limit_note(frame, CHAT_LIMIT_TEXT).pack(fill="x")
        self.chat = self.text_area(frame)
        row, self.chat_entry, self.chat_send = self.entry_row(frame, self.send_chat)
        self.chat_count = ttk.Label(row, style="Muted.TLabel", width=11, anchor="e")
        self.chat_count.pack(side="right", padx=(6, 0))
        self.chat_entry.bind("<KeyRelease>", lambda event: self.update_chat_count())

    def build_message_tab(self):
        frame, header = self.tab("Message")
        self.reader_title = ttk.Label(header, style="Header.TLabel")
        self.reader_title.pack(side="left")
        self.reply_button = ttk.Button(header, text="Reply", command=self.reply)
        self.reply_button.pack(side="right")
        self.post_button = ttk.Button(header, text="New post", command=self.new_post)
        self.post_button.pack(side="right", padx=(0, 4))
        self.home_button = ttk.Button(header, text="Welcome", command=lambda: self.show_home(reload=True))
        self.home_button.pack(side="right", padx=(0, 4))
        self.reader = self.text_area(frame)

    def build_log_tab(self):
        frame, header = self.tab("Server log")
        ttk.Label(
            header, style="Header.TLabel",
            text="Everything the server sends. You can type RetiBBS commands below; ? lists them.",
        ).pack(side="left")
        self.console = self.text_area(frame)
        _row, self.console_entry, self.console_send = self.entry_row(frame, self.send_console)

    def place_sash(self):
        width = self.pane.winfo_width()
        if width < 50:
            self.root.after(50, self.place_sash)
            return
        position = self.settings.get("sash") or int(width * 0.62)
        self.pane.sashpos(0, max(300, min(position, width - 200)))

    # appearance
    def toggle_theme(self):
        self.settings["theme"] = "dark" if self.dark_var.get() else "light"
        self.settings.save()
        self.apply_settings()

    def apply_settings(self):
        size = int(self.settings["font_size"])
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(size=size)
            except tk.TclError:
                pass
        for font in (self.text_font, self.bold_font, self.fixed_font, self.fixed_bold_font):
            font.configure(size=size)
        self.title_font.configure(size=size + 3)
        ttk.Style(self.root).configure("Treeview", rowheight=int(size * 2.2))
        self.palette = PALETTES.get(self.settings["theme"], PALETTES["light"])
        apply_theme(self.root, self.palette, self.menus, (self.chat, self.reader, self.console))
        self.chat.configure(font=self.text_font)
        self.reader.configure(font=self.text_font)
        self.console.configure(font=self.fixed_font)
        for text in (self.chat, self.reader, self.console):
            text.tag_configure("bold", font=self.bold_font)
            text.tag_configure("name", font=self.bold_font)
            text.tag_configure("hint", foreground=self.palette["muted"])
        self.reader.tag_configure("title", font=self.title_font)
        self.reader.tag_configure("meta", foreground=self.palette["muted"])
        self.reader.tag_configure("fixed", font=self.fixed_font)
        self.reader.tag_configure("heading", font=self.bold_font, spacing1=10, spacing3=4)
        self.console.tag_configure("bold", font=self.fixed_bold_font)

    # text output
    def append(self, widget, chunks):
        at_end = widget.yview()[1] > 0.98
        widget.configure(state="normal")
        for chunk, tags in chunks:
            widget.insert("end", chunk, tags)
        widget.configure(state="disabled")
        if at_end:
            widget.see("end")

    def set_text(self, widget, chunks):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")
        self.append(widget, chunks)

    def chat_log(self, text, tag="sys", who=None):
        chunks = [(time.strftime("[%H:%M] "), ("time",))]
        if who:
            chunks.append((who + ": ", ("name", tag)))
            chunks.append((text + "\n", ()))
        else:
            chunks.append((text + "\n", (tag,)))
        self.append(self.chat, chunks)

    def console_write(self, markup_text, tag=None):
        chunks = self.styled(self.console, markup_text, (tag,) if tag else ())
        chunks.append(("\n", ()))
        self.append(self.console, chunks)

    def log(self, text, tag="sys"):
        self.console_write(time.strftime("%H:%M ") + text.replace("[", "\\["), tag)

    def show_notice(self, level, text):
        style = "Error" if level == "error" else "Info"
        self.notice_frame.configure(style=f"{style}.TFrame")
        self.notice_label.configure(text=text, style=f"{style}.TLabel")
        self.notice_close.configure(style=f"{style}.TLabel")
        self.notice_frame.pack(fill="x", after=self.toolbar)
        if self.notice_job:
            self.root.after_cancel(self.notice_job)
        self.notice_job = self.root.after(NOTICE_MS * (2 if level == "error" else 1), self.hide_notice)

    def hide_notice(self):
        self.notice_job = None
        self.notice_frame.pack_forget()

    def error(self, text):
        self.show_notice("error", text)
        self.log(text, "err")

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.show_notice("info", "Copied to the clipboard.")

    # servers
    def remember_server(self, hash_hex, name):
        """Save a BBS to the list. A name typed by the user is kept even when the server announces another."""
        if name:
            self.servers[hash_hex] = {"name": name, "custom": True}
        else:
            # no name typed: use the announced one, or the last one we saw
            announced = self.discovery.snapshot().get(hash_hex, {}).get("name")
            saved = self.servers.get(hash_hex, {})
            last = None if saved.get("custom") else saved.get("name")
            self.servers[hash_hex] = {"name": announced or last or hash_hex, "custom": False}
        self.servers.save()
        if hash_hex == self.server_hash:
            self.server_name = self.servers[hash_hex]["name"]
            self.show_server_name()

    def rename_server(self):
        if not self.server_hash:
            messagebox.showinfo(APP_TITLE, "Connect to a BBS first, or rename it in the Connect dialog.", parent=self.root)
            return
        saved = self.servers.get(self.server_hash, {})
        name = self.ask_name(
            "Rename this BBS", "Name to show for this BBS (empty uses the announced name):",
            saved.get("name", "") if saved.get("custom") else "", allow_empty=True,
        )
        if name is not None:
            self.remember_server(self.server_hash, name)

    def show_server_name(self):
        self.server_label.configure(text=self.server_name or "")
        if self.tree.exists(ROOT_ID):
            self.tree.item(ROOT_ID, text=" " + (self.server_name or ""))
        self.root.title(f"{self.server_name} - {APP_TITLE}" if self.server_name else APP_TITLE)
        if self.client and self.client.connected:
            self.status_var.set(f"Connected to {self.server_name}")

    # connection
    def connect_dialog(self):
        hash_hex = ConnectDialog(self).show()
        if hash_hex:
            self.connect_to(hash_hex)

    def settings_dialog(self):
        SettingsDialog(self).show()

    def connect_to(self, hash_hex):
        self.disconnect(quiet=True)
        name = self.servers.get(hash_hex, {}).get("name") or self.discovery.snapshot().get(hash_hex, {}).get("name")
        self.server_hash = hash_hex
        self.server_name = name or RNS.prettyhexrep(bytes.fromhex(hash_hex))
        self.client = Client(self.identity)
        self.started = False
        self.reset_state()
        self.show_server_name()
        self.account_label.configure(text="connecting...")
        self.log(f"Connecting to {self.server_name}...")
        self.status_var.set(f"Connecting to {self.server_name}...")
        self.client.connect(hash_hex)
        self.rebuild_tree()
        self.show_room()
        self.show_reader_empty()

    def disconnect(self, quiet=False):
        client = self.client
        if client is None:
            return
        self.client = None
        client.disconnect()
        if not quiet:
            self.log("Disconnected.")
        self.offline()

    def offline(self):
        self.status_var.set("Not connected")
        self.rtt_var.set("")
        self.alert_var.set("")
        self.account_label.configure(text="")
        if self.client is None:
            self.server_label.configure(text="Not connected")
            self.root.title(APP_TITLE)
        self.rns_label.configure(image=self.icons["rns_off"])
        self.tree.delete(*self.tree.get_children())
        self.tree.insert("", "end", iid=OFFLINE_ID, text=" Not connected. Click Connect... to pick a BBS.")
        self.set_connected_widgets(False)
        self.show_room()
        self.show_reader_empty()

    def set_connected_widgets(self, online):
        state = "!disabled" if online else "disabled"
        for widget in (self.disconnect_button, self.post_button, self.console_entry, self.console_send):
            widget.state([state])
        self.reply_button.state(["!disabled" if online and self.reading else "disabled"])
        self.update_chat_count()

    def quit(self):
        try:
            self.settings["window"] = self.root.geometry()
            self.settings["sash"] = self.pane.sashpos(0)
            self.settings.save()
        except (tk.TclError, OSError):
            pass
        self.disconnect(quiet=True)
        self.root.destroy()

    def start_session(self):
        """First commands after connecting: name, alert address, then fill the tree."""
        client = self.client
        name, address = self.settings["display_name"], self.settings["alert_address"]
        steps = []
        if name:
            steps.append(f"n {name}")
        if address:
            self.quiet_alert = True
            steps.append(f"d {address}")
        if name:
            # the server cannot answer "h" until the user has a name
            steps.append("h")
        if steps:
            client.goto(MAIN, *steps)  # name and alert commands only work in the main menu
        client.goto(CHAT, "/list")
        client.goto(BOARDS, "lb", "wl")

    def ask_display_name(self):
        if self.client is None:
            return
        name = self.ask_name(
            "Pick a display name",
            "RetiBBS needs a display name before it answers.\nIt is shown on your posts and chat, and each BBS "
            "allows a name only once, so pick another if yours is taken.",
        )
        if name:
            self.settings["display_name"] = name
            self.settings.save()
        if self.client:
            self.start_session()

    # navigation
    def online(self):
        if self.client is None or not self.client.connected or self.client.area is None:
            self.error("Not connected.")
            return False
        return True

    def navigate(self, area, *commands, log=False):
        """Go to an area and run commands, warning first if that drops you out of a chat room."""
        if not self.online():
            return False
        client = self.client
        if client.room and area != CHAT and client.planned_area() == CHAT:
            if not messagebox.askyesno(
                "Leave chat room?",
                f"This takes you out of chat room '{client.room}'.\n\nRetiBBS only keeps you in a room while you "
                "stay in its chat area, and chat is not stored, so you will miss what is said until you join again."
                "\n\nContinue?",
                parent=self.root,
            ):
                return False
        client.goto(area, *commands)
        if log:
            self.notebook.select(LOG_TAB)
        return True

    def open_boards(self):
        self.navigate(BOARDS, "lb", "wl")

    def open_rooms(self):
        self.navigate(CHAT, "/list")

    def on_board(self, board, *commands):
        """Run commands with the given board selected on the server."""
        steps = []
        if self.client.board != board or self.client.planned_area() != BOARDS:
            steps.append((f"cb {board}", "board", board))
        return self.navigate(BOARDS, *steps, *commands)

    def open_board(self, board):
        self.on_board(board, "lm", "lu")

    def read_message(self, board, message_id):
        self.on_board(board, f"r {message_id}")

    def join_room(self, room):
        if self.navigate(CHAT, f"/j {room}", "/list"):
            self.notebook.select(CHAT_TAB)

    def leave_room(self):
        if self.client and self.client.room:
            self.navigate(CHAT, "/l", "/list")

    def refresh_view(self):
        if not self.online():
            return
        tab = self.notebook.index("current")
        if tab == CHAT_TAB or self.client.area == CHAT:
            self.open_rooms()
        elif self.client.board:
            self.open_board(self.client.board)
        else:
            self.open_boards()

    def server_help(self):
        if self.online():
            self.client.run("/?" if self.client.planned_area() == CHAT else "?")
            self.notebook.select(LOG_TAB)

    def new_post(self, board=None):
        if not self.online():
            return
        if not self.boards:
            if self.client.is_admin:
                self.show_notice("info", "Create a board first: right click Message boards > New board.")
            else:
                self.error("This BBS has no boards yet, and only an admin can create one.")
            return
        current = self.client.board if self.client.board != MOTD_BOARD else None
        result = PostDialog(self, self.boards, board or current).show()
        if result:
            self.on_board(*result)

    def reply(self, message=None):
        if not self.online():
            return
        message = message or self.reading
        if message is None:
            self.show_notice("info", "Open a message first: double click it in the list on the right.")
            return
        result = PostDialog(self, self.boards, reply_to=message).show()
        if result:
            self.on_board(*result)

    def set_watch(self, board, on):
        if on and not self.client.alert_address:
            if messagebox.askyesno(
                "Board alerts",
                "Alerts arrive as LXMF messages in another app, such as Sideband, Columba or MeshChat. Set that "
                "app's LXMF address in Settings first.\n\nOpen Settings now?",
                parent=self.root,
            ):
                self.settings_dialog()
            return
        # RetiBBS watches the board you are in, whatever name you give, so select it first
        self.on_board(board, "w" if on else "uw", "wl")

    def send_alert_test(self, address):
        commands = [] if self.client and self.client.alert_address == address else [f"d {address}"]
        self.settings["alert_address"] = address
        self.settings.save()
        if self.navigate(MAIN, *commands, "td", "h"):
            self.show_notice("info", "Test requested. Check your LXMF app; it can take a minute over slow links.")

    def load_users(self):
        if not self.online():
            return
        if not self.client.is_admin:
            self.show_notice("info", "Only admins can list the users of a BBS.")
            return
        self.navigate(MAIN, "lu")

    def make_admin(self, user):
        name = user["name"] or user["hash"]
        if messagebox.askyesno(
            "Make admin",
            f"Give {name} admin rights on {self.server_name}?\n\nAdmins can create and delete boards and make other "
            "admins. RetiBBS has no command to take admin rights away again.",
            parent=self.root,
        ):
            self.navigate(MAIN, f"a {user['hash']}", "lu")

    def update_chat_count(self):
        client = self.client
        in_room = bool(client and client.connected and client.room)
        limit = client.chat_limit() if in_room else None
        used = Client.chat_cost(self.chat_entry.get())
        over = limit is not None and used > limit
        self.chat_count.configure(
            text=f"{used} / {limit}" if limit is not None else "", style="Over.TLabel" if over else "Muted.TLabel"
        )
        self.chat_entry.state(["!disabled" if in_room else "disabled"])
        self.chat_send.state(["!disabled" if in_room and not over else "disabled"])

    def send_chat(self):
        text = self.chat_entry.get().strip()
        if not text or not self.online():
            return
        if text.startswith("/"):
            self.navigate(CHAT, text)
        elif not self.client.room:
            self.show_notice("info", "Join a room first: double click one in the list on the right.")
            return
        elif Client.chat_cost(text) > (self.client.chat_limit() or 0):
            self.error("Too long for one chat packet. Shorten the message.")
            return
        else:
            self.client.run(text)
        self.chat_entry.delete(0, "end")
        self.update_chat_count()

    def send_console(self):
        text = self.console_entry.get().strip()
        if not text or not self.online():
            return
        self.console_write("> " + text.replace("[", "\\["), "sys")
        self.client.run(text)
        self.console_entry.delete(0, "end")

    # views
    def show_room(self):
        client = self.client
        room = client.room if client else None
        if room:
            count = dict(self.rooms).get(room)
            self.room_label.configure(text=room)
            self.room_hint.configure(text=f"{count} here" if count else "")
            self.notebook.tab(CHAT_TAB, text=f"Chat: {room}")
            self.leave_button.state(["!disabled"])
        else:
            self.room_label.configure(text="Not in a chat room")
            hint = "Double click a room on the right to join it." if client else ""
            self.room_hint.configure(text=hint)
            self.notebook.tab(CHAT_TAB, text="Chat")
            self.leave_button.state(["disabled"])
        self.update_chat_count()

    def show_reader_empty(self):
        self.show_home()

    def show_home(self, reload=False):
        """The Message tab before a message is opened: message of the day and the server's welcome message."""
        self.reading = None
        self.reply_button.state(["disabled"])
        client = self.client
        if client is None:
            self.reader_title.configure(text="Not connected")
            self.notebook.tab(MESSAGE_TAB, text="Message")
            self.set_text(self.reader, [])
            self.home_button.state(["disabled"])
            return
        self.home_button.state(["!disabled"])
        self.reader_title.configure(text="")
        self.notebook.tab(MESSAGE_TAB, text="Welcome")
        chunks = [(self.server_name + "\n", ("title",)), ("Message of the day\n", ("heading",))]
        if self.motd:
            motd = self.motd
            chunks.append((motd["topic"] + "\n", ("bold",)))
            chunks.append((f"{motd['author']}  \u00b7  {motd['time']}\n\n", ("meta",)))
            chunks.append((motd["body"] + "\n", ()))
        elif self.motd_state:
            chunks.append(("Loading...\n", ("hint",)))
        elif MOTD_BOARD in self.boards:
            chunks.append(("The motd board has no posts yet.\n", ("hint",)))
        else:
            chunks.append((
                f"None. Admins: create a board named {MOTD_BOARD}; its newest post shows here.\n", ("hint",)
            ))
        chunks.append(("Welcome message\n", ("heading",)))
        if self.welcome:
            chunks += self.styled(self.reader, self.welcome, ("fixed",))
            chunks.append(("\n", ()))
        else:
            chunks.append(("The server has not sent one yet.\n", ("hint",)))
        chunks.append(("\nDouble click a message in the list on the right to read it.", ("hint",)))
        self.set_text(self.reader, chunks)
        self.reader.see("1.0")
        if reload:
            self.notebook.select(MESSAGE_TAB)
            self.load_motd()

    def load_motd(self):
        """Fetch the newest post on the motd board, unless that would take the user out of a chat room."""
        client = self.client
        if not client or not client.connected or MOTD_BOARD not in self.boards or self.motd_state:
            return
        if client.room and client.planned_area() == CHAT:
            return
        self.motd_checked = True
        self.motd_state = "listing"
        self.on_board(MOTD_BOARD, "lm")

    def styled(self, widget, markup_text, base_tags=()):
        """Chunks for a text widget from Rich markup, with a tag per color."""
        chunks = []
        for chunk, color, bold in styled_runs(markup_text):
            tags = list(base_tags)
            if color:
                name = "c" + color.lstrip("#")
                if (widget, name) not in self.color_tags:
                    widget.tag_configure(name, foreground=color)
                    self.color_tags.add((widget, name))
                tags.append(name)
            if bold:
                tags.append("bold")
            chunks.append((chunk, tuple(tags)))
        return chunks

    def show_message(self, message):
        message["board"] = self.client.board
        self.reading = message
        chunks = [(message["topic"] + "\n", ("title",))]
        meta = f"{message['author']}  ·  {message['time']}  ·  #{message['id']} in {message['board']}"
        chunks.append((meta + "\n\n", ("meta",)))
        chunks.append((message["body"] + "\n", ()))
        if message["replies"]:
            count = len(message["replies"])
            chunks.append((f"\n{count} {'reply' if count == 1 else 'replies'}\n", ("bold",)))
            for reply in message["replies"]:
                chunks.append((f"\n{reply['author']}", ("name",)))
                chunks.append((f"  {reply['time']}\n", ("meta",)))
                chunks.append((reply["body"] + "\n", ()))
        self.set_text(self.reader, chunks)
        self.reader.see("1.0")
        self.reader_title.configure(text=f"{message['board']} › {message['topic']}")
        topic = message["topic"] if len(message["topic"]) <= 22 else message["topic"][:21] + "…"
        self.notebook.tab(MESSAGE_TAB, text=f"Message: {topic}")
        self.reply_button.state(["!disabled"])
        self.notebook.select(MESSAGE_TAB)
        self.unread.get(message["board"], set()).discard(message["id"])
        self.fill_boards()

    def update_account(self):
        client = self.client
        if client is None:
            return
        who = client.user_name or self.settings["display_name"] or "no name yet"
        admin = ", admin" if client.is_admin else ""
        self.account_label.configure(text=f"signed in as {who}{admin}")
        self.status_var.set(f"Connected to {self.server_name}")
        if client.alert_address is None:
            self.alert_var.set("")
        else:
            self.alert_var.set("Board alerts: " + ("on" if client.alert_address else "no address set"))
        if self.tree.exists(ROOT_ID):
            self.fill_boards()  # the empty board hint depends on admin rights
            self.fill_users()

    # tree
    def rebuild_tree(self):
        tree = self.tree
        tree.delete(*tree.get_children())
        if self.client is None:
            return
        tree.insert("", "end", iid=ROOT_ID, text=" " + self.server_name, image=self.icons["server"], open=True)
        tree.insert(ROOT_ID, "end", iid=BOARDS_ID, text=" Message boards", open=True)
        tree.insert(ROOT_ID, "end", iid=ROOMS_ID, text=" Chat rooms", open=True)
        self.fill_boards()
        self.fill_rooms()
        self.fill_users()

    def fill_boards(self):
        if not self.tree.exists(BOARDS_ID):
            return
        opened = {item for item in self.tree.get_children(BOARDS_ID) if self.tree.item(item, "open")}
        self.tree.delete(*self.tree.get_children(BOARDS_ID))
        current = self.client.board if self.client else None
        for board in self.boards:
            iid = "board:" + board
            unread = self.unread.get(board)
            label = f" {board}" + (f"  ({len(unread)} new)" if unread else "")
            label += "  · alerts on" if board in self.watched else ""
            self.tree.insert(
                BOARDS_ID, "end", iid=iid, text=label, image=self.icons["channel"],
                tags=("unread",) if unread else (), open=iid in opened or board == current,
            )
            self.fill_messages(board)
        if not self.boards:
            admin = bool(self.client and self.client.is_admin)
            hint = "right click Message boards to create one" if admin else "only an admin can create one"
            self.tree.insert(BOARDS_ID, "end", iid="boards:none", text=f"(no boards yet; {hint})")

    def fill_messages(self, board):
        iid = "board:" + board
        if not self.tree.exists(iid) or board not in self.messages:
            return
        page, pages, messages = self.messages[board]
        unread = self.unread.get(board, set())
        if page > 1:
            self.tree.insert(iid, "end", iid=f"prev:{board}", text="‹ Newer messages")
        for message in messages:
            replies = message["replies"]
            text = f"{message['topic']}  by {message['author']}" + (f"  ({replies})" if replies else "")
            tags = ("unread",) if message["id"] in unread else ()
            self.tree.insert(iid, "end", iid=f"msg:{board}:{message['id']}", text=text, tags=tags)
        if page < pages:
            self.tree.insert(iid, "end", iid=f"next:{board}", text=f"Older messages ›  (page {page} of {pages})")
        if not messages:
            self.tree.insert(iid, "end", iid=f"empty:{board}", text="(no messages yet)")

    def fill_rooms(self):
        if not self.tree.exists(ROOMS_ID):
            return
        self.tree.delete(*self.tree.get_children(ROOMS_ID))
        current = self.client.room if self.client else None
        names = [name for name, _count in self.rooms]
        rooms = list(self.rooms)
        if current and current not in names:
            rooms.append((current, 1))
        for name, count in rooms:
            you = ", you are here" if name == current else ""
            self.tree.insert(
                ROOMS_ID, "end", iid="room:" + name, text=f" {name}  ({count}{you})",
                image=self.icons["user_idle"] if name == current else self.icons["channel"],
                tags=("self",) if name == current else (),
            )
        if not rooms:
            self.tree.insert(ROOMS_ID, "end", iid="rooms:none", text="(none open; right click to start one)")

    def fill_users(self):
        """Admins get a Users branch; RetiBBS only lists users to admins."""
        admin = bool(self.client and self.client.is_admin)
        if not admin:
            if self.tree.exists(USERS_ID):
                self.tree.delete(USERS_ID)
            return
        if not self.tree.exists(USERS_ID):
            self.tree.insert(ROOT_ID, "end", iid=USERS_ID, text=" Users", open=True)
        self.tree.delete(*self.tree.get_children(USERS_ID))
        if self.users is None:
            self.tree.insert(USERS_ID, "end", iid="users:load", text="(double click to load)")
            return
        for user in sorted(self.users, key=lambda user: (user["name"] or "~").lower()):
            name = user["name"] or "(no name) " + user["hash"][:8]
            self.tree.insert(
                USERS_ID, "end", iid="user:" + user["hash"], text=f" {name}" + ("  (admin)" if user["admin"] else ""),
                image=self.icons["user_idle"],
            )

    def tree_open(self, event=None):
        selection = self.tree.selection()
        if not selection or selection[0] == OFFLINE_ID:
            if selection:
                self.connect_dialog()
            return "break"
        if not self.online():
            return "break"
        iid = selection[0]
        kind, _, rest = iid.partition(":")
        if iid == BOARDS_ID:
            self.open_boards()
        elif iid in (ROOMS_ID, "rooms:none"):
            self.open_rooms()
        elif iid in (USERS_ID, "users:load"):
            self.load_users()
        elif kind == "board":
            self.open_board(rest)
        elif kind == "msg":
            board, _, message_id = rest.rpartition(":")
            self.read_message(board, int(message_id))
        elif kind == "next":
            self.on_board(rest, ">", "lu")
        elif kind == "prev":
            self.on_board(rest, "<", "lu")
        elif kind == "room":
            if self.client.room == rest:
                self.notebook.select(CHAT_TAB)
            else:
                self.join_room(rest)
        return "break"

    def tree_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or self.client is None:
            return
        self.tree.selection_set(iid)
        kind, _, rest = iid.partition(":")
        menu = tk.Menu(self.root, tearoff=0)
        admin = self.client.is_admin
        if iid == ROOT_ID:
            menu.add_command(label="Rename...", command=self.rename_server)
            menu.add_command(label="Copy address", command=lambda: self.copy(self.server_hash))
            menu.add_command(label="Disconnect", command=self.disconnect)
        elif iid in (BOARDS_ID, "boards:none"):
            menu.add_command(label="Refresh", command=self.open_boards)
            menu.add_command(label="New post...", command=self.new_post)
            if admin:
                menu.add_command(label="New board...", command=self.new_board)
        elif kind == "board":
            menu.add_command(label="Open", command=lambda: self.open_board(rest))
            menu.add_command(label="New post...", command=lambda: self.new_post(rest))
            menu.add_separator()
            watched = tk.BooleanVar(value=rest in self.watched)
            menu.add_checkbutton(
                label="Alert me about new posts", variable=watched, command=lambda: self.set_watch(rest, watched.get())
            )
            menu.watched = watched  # keep the variable alive while the menu is open
            if admin:
                menu.add_separator()
                menu.add_command(label="Delete board...", command=lambda: self.delete_board(rest))
        elif kind == "msg":
            board, _, message_id = rest.rpartition(":")
            menu.add_command(label="Read", command=lambda: self.read_message(board, int(message_id)))
        elif iid in (ROOMS_ID, "rooms:none"):
            menu.add_command(label="Refresh", command=self.open_rooms)
            menu.add_command(label="Start or join a room...", command=self.ask_room)
        elif kind == "room":
            if self.client.room == rest:
                menu.add_command(label="Leave", command=self.leave_room)
            else:
                menu.add_command(label="Join", command=lambda: self.join_room(rest))
        elif iid in (USERS_ID, "users:load"):
            menu.add_command(label="Refresh", command=self.load_users)
        elif kind == "user":
            user = next((user for user in self.users or [] if user["hash"] == rest), None)
            if user and not user["admin"]:
                menu.add_command(label="Make admin...", command=lambda: self.make_admin(user))
            menu.add_command(label="Copy user hash", command=lambda: self.copy(rest))
        else:
            return
        self.palette_menu(menu)
        menu.tk_popup(event.x_root, event.y_root)

    def palette_menu(self, menu):
        palette = self.palette
        menu.configure(bg=palette["btn"], fg=palette["fg"], selectcolor=palette["fg"])
        menu.configure(activebackground=palette["select"], activeforeground=palette["selfg"])

    def ask_name(self, title, prompt, initial="", allow_empty=False):
        dialog = Dialog(self.root, title)
        ttk.Label(dialog.body, text=prompt, justify="left").grid(row=0, column=0, sticky="w")
        value = tk.StringVar(value=initial)
        entry = ttk.Entry(dialog.body, textvariable=value, width=36)
        entry.grid(row=1, column=0, sticky="ew", pady=4)
        entry.focus_set()
        entry.bind("<Return>", lambda event: dialog.ok())
        original_ok = dialog.ok

        def ok():
            text = value.get().strip()
            dialog.result = text if text or allow_empty else None
            original_ok()

        dialog.ok = ok
        dialog.buttons()  # after replacing ok, so the OK button calls the new one
        return dialog.show()

    def ask_room(self):
        name = self.ask_name("Chat room", "Room name. A new room is started if none has this name:")
        if name:
            self.join_room(name)

    def new_board(self):
        name = self.ask_name("New board", "Board name: 3 to 20 letters or digits, no spaces.")
        if not name:
            return
        if not BOARD_NAME.fullmatch(name):
            self.error("RetiBBS board names are 3 to 20 letters or digits, with no spaces or symbols.")
            return
        self.navigate(BOARDS, f"nb {name}", "lb")

    def delete_board(self, board):
        if messagebox.askyesno(
            "Delete board", f"Delete board '{board}' and every message in it?\n\nThis cannot be undone.",
            parent=self.root,
        ):
            self.navigate(BOARDS, f"db {board}", "lb")

    # events from the client
    def refresh(self):
        try:
            client = self.client
            if client is not None:
                self.update_server_name()
                while True:
                    try:
                        event = client.events.get_nowait()
                    except queue.Empty:
                        break
                    if client is not self.client:
                        break
                    self.handle_event(event)
        except Exception as error:
            RNS.log(f"Event handling failed: {type(error).__name__}: {error}", RNS.LOG_ERROR)
        finally:
            self.root.after(REFRESH_MS, self.refresh)

    def update_server_name(self):
        """Use the announced name once an announce arrives, unless the user named this BBS."""
        if self.servers.get(self.server_hash, {}).get("custom"):
            return
        name = self.discovery.snapshot().get(self.server_hash, {}).get("name")
        if not name or name == self.server_name:
            return
        self.server_name = name
        if self.server_hash in self.servers:
            self.servers[self.server_hash]["name"] = name
            self.servers.save()
        self.show_server_name()

    def handle_event(self, event):
        kind = event[0]
        client = self.client
        if kind == "status":
            self.status_var.set(event[1])
            self.log(event[1])
        elif kind == "failed":
            self.error(event[1])
            self.client = None
            self.offline()
        elif kind == "connected":
            hops = event[1]
            path = f", {hops} hop{'s' if hops != 1 else ''} away" if hops is not None else ""
            self.log(f"Connected to {self.server_name}{path}.")
            self.rns_label.configure(image=self.icons["rns_online"])
            self.set_connected_widgets(True)
            self.update_account()
        elif kind == "disconnected":
            self.error(f"Connection {event[1]}.")
            self.client = None
            self.offline()
        elif kind == "area":
            if not self.started:
                self.started = True
                if self.settings["display_name"]:
                    self.start_session()
                else:
                    self.root.after(10, self.ask_display_name)
        elif kind == "board":
            self.fill_boards()
        elif kind in ("room", "joined", "left"):
            if kind == "left" and event[1]:
                self.chat_log(f"You left {event[1]}.")
            self.fill_rooms()
            self.show_room()
        elif kind in ("hello", "named"):
            if kind == "named":
                client.user_name = self.settings["display_name"] or client.user_name
            self.update_account()
        elif kind == "boards":
            self.boards = event[1]
            if MOTD_BOARD not in self.boards:
                self.motd = None
            self.fill_boards()
            if not self.motd_checked and MOTD_BOARD in self.boards:
                self.load_motd()
            elif self.reading is None:
                self.show_home()
        elif kind == "welcome":
            self.welcome = event[1]
            if self.reading is None:
                self.show_home()
        elif kind == "watchlist":
            self.watched = set(event[1])
            self.fill_boards()
        elif kind == "watch_changed":
            (self.watched.add if event[2] else self.watched.discard)(event[1])
            self.fill_boards()
        elif kind == "users":
            self.users = event[1]
            self.fill_users()
        elif kind == "alert_set":
            client.alert_address = self.settings["alert_address"]
            self.update_account()
        elif kind == "notice":
            if self.quiet_alert and event[2].startswith("Destination address updated"):
                self.quiet_alert = False
            else:
                self.show_notice(event[1], event[2])
            if NAME_TAKEN.match(event[2]):
                # keep the name the server has; without one it does not answer, so ask for another
                self.settings["display_name"] = client.user_name or ""
                self.settings.save()
                if not client.user_name:
                    self.root.after(10, self.ask_display_name)
        elif kind == "messages":
            _, board, page, pages, messages = event
            self.messages[board] = (page, pages, messages)
            if board == MOTD_BOARD and self.motd_state == "listing":
                if messages:
                    newest = max(message["id"] for message in messages)
                    self.motd_state = ("reading", newest)
                    client.run(f"r {newest}")
                else:
                    self.motd_state, self.motd = None, None
                    if self.reading is None:
                        self.show_home()
            self.fill_boards()
            item = "board:" + board
            if self.tree.exists(item):
                self.tree.item(item, open=True)
        elif kind == "unread":
            self.unread[event[1]] = set(event[2])
            self.fill_boards()
        elif kind == "message":
            message = event[1]
            if self.motd_state == ("reading", message["id"]) and client.board == MOTD_BOARD:
                message["board"] = MOTD_BOARD
                self.motd, self.motd_state = message, None
                if self.reading is None:
                    self.show_home()
            else:
                self.show_message(message)
        elif kind == "posted":
            self.show_notice("info", "Posted.")
            if self.reading and self.reading.get("board") == client.board:
                client.run(f"r {self.reading['id']}")
            if client.board == MOTD_BOARD and not self.motd_state:
                self.motd_state = "listing"  # a new message of the day
            client.run("lm", "lu")
        elif kind == "rooms":
            self.rooms = event[1]
            self.fill_rooms()
            self.show_room()
        elif kind == "chat":
            _, room, who, text, mine = event
            if mine:
                self.chat_log(text, "me", who=client.user_name or "You")
            elif who:
                self.chat_log(text, "name", who=who)
            else:
                self.chat_log(text, "sys")
        elif kind == "text":
            self.console_write(event[1])
        elif kind == "cls":
            self.console_write("─" * 40, "hint")
        elif kind == "rtt":
            self.rtt_var.set(f"Round trip {event[1]:.2f} s")
        elif kind == "error":
            self.error(event[1])

    def show_limits(self):
        limit = self.client.packet_limit if self.client and self.client.connected else None
        size = f"{limit} bytes on this connection" if limit else "a few hundred bytes, depending on the link"
        dialog = Dialog(self.root, "Server limits")
        ttk.Label(
            dialog.body, wraplength=520, justify="left",
            text="These come from the RetiBBS server, not from this client.",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        items = (
            ("Posts and replies", f"Each must fit in one Reticulum packet, topic included: {size}. The size "
                                  "depends on the slowest link to the server: a few hundred bytes over LoRa or "
                                  "packet radio, far more over TCP. Longer text is refused. Posts cannot be edited "
                                  "or deleted, and only admins can delete a board."),
            ("Chat", "Live only and not stored. You see only what is said while you are in the room. Each chat "
                     "message must also fit in one packet, with the room and your name."),
            ("Staying in a room", "You stay in a chat room only while you are in the chat area. Opening the boards, "
                                  "changing your name or alert address, or listing users takes you out of the room."),
            ("Files", "RetiBBS has no file sharing."),
            ("Board alerts", "Sent as LXMF messages to another app; this client cannot receive them. An address "
                             "can be replaced but not removed."),
            ("Names", "You need a display name before the server answers. Each BBS allows a name only once. "
                      "Board names are 3 to 20 letters or digits."),
            ("Admins", "Only admins can list users, create or delete boards, and make other admins. RetiBBS has "
                       "no command to take admin rights away."),
        )
        for row, (title, text) in enumerate(items, start=1):
            ttk.Label(dialog.body, text=title, font=self.bold_font).grid(row=row, column=0, sticky="nw", pady=(4, 0))
            ttk.Label(dialog.body, text=text, wraplength=520, justify="left").grid(
                row=row, column=1, sticky="w", padx=(10, 0), pady=(4, 0)
            )
        row = ttk.Frame(dialog.body)
        row.grid(row=99, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(row, text="Close", command=dialog.ok).pack(side="right")
        dialog.show()

    def about(self):
        AboutDialog(self).show()


def main():
    parser = argparse.ArgumentParser(description="Desktop client for RetiBBS")
    parser.add_argument("--reticulum-config", default=None, help="alternative Reticulum config directory")
    parser.add_argument("--server", default=None, help="destination hash to connect to at start")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    RNS.Reticulum(args.reticulum_config, loglevel=RNS.LOG_WARNING + args.verbose)
    identity = load_identity()
    discovery = Discovery()
    RNS.Transport.register_announce_handler(discovery)

    root = tk.Tk(className="retibbs-gui")
    app = App(root, identity, prefs.settings(), prefs.servers(), discovery)
    if args.server:
        root.after(200, lambda: app.connect_to(clean_hash(args.server)))
    root.mainloop()
    RNS.exit()


if __name__ == "__main__":
    main()
