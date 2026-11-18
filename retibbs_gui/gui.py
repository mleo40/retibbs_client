"""Tk desktop client for RetiBBS with partyline's look and layout."""

import argparse
import os
import queue
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter import font as tkfont

import RNS

from . import prefs
from .client import BOARDS, CHAT, MAIN, Client, Discovery
from .parse import styled_runs
from .theme import PALETTES, apply_theme

APP_TITLE = "RetiBBS"
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
REFRESH_MS = 100
ROOT_ID, BOARDS_ID, ROOMS_ID = "server", "boards", "rooms"


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
        ttk.Button(row, text=ok_text, command=self.ok).pack(side="right")
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
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(body)
        self.notebook.grid(row=0, column=0, columnspan=3, sticky="nsew")

        self.saved = self.make_tree(("name", "hash"), ("Name", "Destination hash"))
        self.discovered = self.make_tree(("name", "hash", "hops", "seen"), ("Name", "Destination hash", "Hops", "Last seen"))
        self.notebook.add(self.saved.master, text="Favourites")
        self.notebook.add(self.discovered.master, text="Discovered")

        row = ttk.Frame(body)
        row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(row, text="Hash:").pack(side="left")
        self.hash_var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.hash_var, width=36)
        entry.pack(side="left", fill="x", expand=True, padx=4)
        entry.bind("<Return>", lambda event: self.ok())
        ttk.Button(row, text="Save", command=self.save).pack(side="left")
        ttk.Button(row, text="Remove", command=self.remove).pack(side="left", padx=(4, 0))
        self.buttons("Connect")
        self.fill_saved()
        self.tick()
        if not self.app.servers:
            self.notebook.select(1)
        self.geometry("640x380")

    def make_tree(self, columns, headings):
        frame = ttk.Frame(self.notebook)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
            tree.column(column, width=80 if column in ("hops",) else 160, stretch=column != "hops")
        tree.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(frame, command=tree.yview).pack(side="right", fill="y")
        tree.bind("<<TreeviewSelect>>", lambda event: self.picked(tree))
        tree.bind("<Double-1>", lambda event: self.ok())
        return tree

    def picked(self, tree):
        selection = tree.selection()
        if selection:
            self.hash_var.set(selection[0])

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

    def clean_hash(self):
        return self.hash_var.get().strip().strip("<>").replace(":", "").lower()

    def save(self):
        hash_hex = self.clean_hash()
        if len(hash_hex) != 32:
            messagebox.showerror("Save", "Enter or pick a 32 character destination hash.", parent=self)
            return
        known = self.app.discovery.snapshot().get(hash_hex, {})
        saved_name = self.app.servers.get(hash_hex, {}).get("name")
        self.app.servers[hash_hex] = {"name": known.get("name") or saved_name or hash_hex}
        self.app.servers.save()
        self.fill_saved()
        self.notebook.select(0)

    def remove(self):
        selection = self.saved.selection()
        if selection:
            self.app.servers.pop(selection[0], None)
            self.app.servers.save()
            self.fill_saved()

    def ok(self):
        hash_hex = self.clean_hash()
        if len(hash_hex) != 32:
            messagebox.showerror("Connect", "Enter or pick a 32 character destination hash.", parent=self)
            return
        self.result = hash_hex
        self.destroy()


class PostDialog(Dialog):
    def __init__(self, app, boards, board=None, reply_to=None):
        title = f"Reply to message {reply_to['id']}" if reply_to else "New post"
        super().__init__(app.root, title)
        self.app = app
        self.reply_to = reply_to
        body = self.body
        body.columnconfigure(1, weight=1)
        body.rowconfigure(2, weight=1)
        if reply_to:
            ttk.Label(body, text=f"Re: {reply_to['topic']}").grid(row=0, column=0, columnspan=2, sticky="w")
        else:
            ttk.Label(body, text="Board").grid(row=0, column=0, sticky="w")
            self.board = ttk.Combobox(body, values=boards, state="readonly")
            self.board.grid(row=0, column=1, sticky="ew", pady=2)
            if board in boards:
                self.board.set(board)
            elif boards:
                self.board.set(boards[0])
            ttk.Label(body, text="Topic").grid(row=1, column=0, sticky="w")
            self.topic = ttk.Entry(body)
            self.topic.grid(row=1, column=1, sticky="ew", pady=2)
            self.topic.focus_set()
        self.text = tk.Text(body, width=60, height=10, wrap="word", font=app.text_font)
        self.text.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        apply_theme(app.root, app.palette, texts=[self.text])
        self.count = ttk.Label(body, foreground=app.palette["muted"])
        self.count.grid(row=3, column=0, columnspan=2, sticky="w")
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
        link = self.app.client.link if self.app.client else None
        limit = link.mdu if link else None
        used = len(command.encode("utf-8"))
        self.count.configure(text=f"{used} of {limit} bytes" if limit else f"{used} bytes")

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
            messagebox.showerror(
                self.title(),
                "Too long. RetiBBS takes each post as a single Reticulum packet, so keep it under the byte limit shown.",
                parent=self,
            )
            return
        self.result = (None if self.reply_to else self.board.get(), command)
        self.destroy()


class SettingsDialog(Dialog):
    def __init__(self, app):
        super().__init__(app.root, "Settings")
        self.app = app
        body = self.body
        ttk.Label(body, text="Display name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=app.settings["display_name"])
        ttk.Entry(body, textvariable=self.name_var, width=30).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(body, text="Font size").grid(row=1, column=0, sticky="w")
        self.size_var = tk.IntVar(value=app.settings["font_size"])
        ttk.Spinbox(body, from_=8, to=20, textvariable=self.size_var, width=5).grid(row=1, column=1, sticky="w", pady=2)
        self.dark_var = tk.BooleanVar(value=app.settings["theme"] == "dark")
        ttk.Checkbutton(body, text="Dark mode", variable=self.dark_var).grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(body, text="Identity").grid(row=3, column=0, sticky="w")
        ttk.Label(body, text=RNS.prettyhexrep(app.identity.hash)).grid(row=3, column=1, sticky="w")
        self.buttons()

    def ok(self):
        settings = self.app.settings
        new_name = self.name_var.get().strip()
        changed_name = new_name and new_name != settings["display_name"]
        settings["display_name"] = new_name
        try:
            settings["font_size"] = max(8, min(20, int(self.size_var.get())))
        except (tk.TclError, ValueError):
            pass
        settings["theme"] = "dark" if self.dark_var.get() else "light"
        settings.save()
        self.app.dark_var.set(settings["theme"] == "dark")
        self.app.apply_settings()
        if changed_name and self.app.client and self.app.client.connected:
            self.app.navigate(MAIN, f"n {new_name}")
        self.destroy()


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
        self.boards = []
        self.messages = {}  # board -> (page, pages, [message])
        self.unread = {}  # board -> set of ids
        self.rooms = []
        self.reading = None
        self.started = False
        self.palette = PALETTES.get(settings["theme"], PALETTES["light"])
        self.color_tags = set()

        root.title(APP_TITLE)
        root.minsize(720, 440)
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
        self.build_statusbar()
        self.build_body()
        self.apply_settings()
        self.chat_log("Welcome. Server > Connect... to pick a BBS.", "sys")
        self.set_connected_widgets(False)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(REFRESH_MS, self.refresh)

    # building
    def build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        server_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Server", menu=server_menu)
        server_menu.add_command(label="Connect...", accelerator="Ctrl+O", command=self.connect_dialog)
        server_menu.add_command(label="Disconnect", accelerator="Ctrl+D", command=self.disconnect)
        server_menu.add_separator()
        server_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.quit)

        bbs_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="BBS", menu=bbs_menu)
        bbs_menu.add_command(label="Message boards", command=self.open_boards)
        bbs_menu.add_command(label="Chat rooms", command=self.open_rooms)
        bbs_menu.add_command(label="New post...", accelerator="Ctrl+N", command=self.new_post)
        bbs_menu.add_separator()
        bbs_menu.add_command(label="Watchlist", command=lambda: self.navigate(BOARDS, "wl", console=True))
        bbs_menu.add_command(label="Who am I", command=lambda: self.navigate(MAIN, "h", console=True))
        bbs_menu.add_command(label="Server help", command=self.server_help)

        configure_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Configure", menu=configure_menu)
        configure_menu.add_command(label="Settings...", command=lambda: SettingsDialog(self).show())
        self.dark_var = tk.BooleanVar(value=self.settings["theme"] == "dark")
        configure_menu.add_checkbutton(label="Dark Mode", variable=self.dark_var, command=self.toggle_theme)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.about)

        self.menus = [menubar, server_menu, bbs_menu, configure_menu, help_menu]
        self.root.bind("<Control-o>", lambda event: self.connect_dialog())
        self.root.bind("<Control-d>", lambda event: self.disconnect())
        self.root.bind("<Control-q>", lambda event: self.quit())
        self.root.bind("<Control-n>", lambda event: self.new_post())

    def build_toolbar(self):
        toolbar = ttk.Frame(self.root, padding=(4, 3))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Connect", command=self.connect_dialog).pack(side="left")
        self.disconnect_button = ttk.Button(toolbar, text="Disconnect", command=self.disconnect)
        self.disconnect_button.pack(side="left", padx=(2, 0))
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=6)
        self.online_buttons = []
        for text, command in (
            ("Boards", self.open_boards),
            ("Chat", self.open_rooms),
            ("New post", self.new_post),
            ("Reply", self.reply),
            ("Refresh", self.refresh_view),
        ):
            button = ttk.Button(toolbar, text=text, command=command)
            button.pack(side="left", padx=(0, 2))
            self.online_buttons.append(button)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(toolbar, text="Settings", command=lambda: SettingsDialog(self).show()).pack(side="left")
        self.where_var = tk.StringVar()
        ttk.Label(toolbar, textvariable=self.where_var).pack(side="right", padx=6)

    def build_statusbar(self):
        bar = ttk.Frame(self.root, padding=(6, 2))
        bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="Not connected")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        self.rns_label = ttk.Label(bar, image=self.icons["rns_off"])
        self.rns_label.pack(side="right")
        self.rtt_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.rtt_var).pack(side="right", padx=8)

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
        self.chat, self.chat_entry = self.text_tab("Chat", self.send_chat, "Send")
        self.reader, _ = self.text_tab("Reader", None, None)
        self.console, self.console_entry = self.text_tab("Console", self.send_console, "Send")
        self.reader_actions = ttk.Frame(self.reader.master)
        self.reader_actions.pack(fill="x", pady=(3, 0), before=self.reader)
        ttk.Button(self.reader_actions, text="Reply", command=self.reply).pack(side="left")
        self.reader_title = ttk.Label(self.reader_actions)
        self.reader_title.pack(side="left", padx=8)

        self.tree = ttk.Treeview(right, show="tree", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(right, command=self.tree.yview).pack(side="right", fill="y")
        self.tree.tag_configure("self", font=self.bold_font)
        self.tree.tag_configure("unread", font=self.bold_font)
        self.tree.bind("<Double-1>", self.tree_open)
        self.tree.bind("<Return>", self.tree_open)
        self.tree.bind("<Button-3>", self.tree_menu)

    def text_tab(self, title, send, button):
        frame = ttk.Frame(self.notebook, padding=(0, 3, 0, 0))
        self.notebook.add(frame, text=title)
        text = tk.Text(frame, wrap="word", state="disabled", height=10)
        scroll = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        entry = None
        if send:
            row = ttk.Frame(frame)
            row.pack(side="bottom", fill="x", pady=(3, 0))
            entry = ttk.Entry(row)
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<Return>", lambda event: send())
            ttk.Button(row, text=button, command=send).pack(side="left", padx=(3, 0))
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        return text, entry

    def place_sash(self):
        width = self.pane.winfo_width()
        if width < 50:
            self.root.after(50, self.place_sash)
            return
        position = self.settings.get("sash") or int(width * 0.62)
        self.pane.sashpos(0, max(250, min(position, width - 180)))

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
        self.text_font.configure(size=size)
        self.bold_font.configure(size=size)
        self.fixed_font.configure(size=size)
        ttk.Style(self.root).configure("Treeview", rowheight=int(size * 2.2))
        self.palette = PALETTES.get(self.settings["theme"], PALETTES["light"])
        apply_theme(self.root, self.palette, self.menus, (self.chat, self.reader, self.console))
        self.chat.configure(font=self.text_font)
        self.reader.configure(font=self.text_font)
        self.console.configure(font=self.fixed_font)
        for text in (self.chat, self.reader, self.console):
            text.tag_configure("bold", font=self.bold_font)
            text.tag_configure("name", font=self.bold_font)
        self.title_font.configure(size=size + 3)
        self.fixed_bold_font.configure(size=size)
        self.reader.tag_configure("title", font=self.title_font)
        self.reader.tag_configure("meta", foreground=self.palette["muted"])
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

    def chat_log(self, text, tag="sys", who=None):
        chunks = [(time.strftime("[%H:%M] "), ("time",))]
        if who:
            chunks.append((who + ": ", ("name", tag)))
            chunks.append((text + "\n", ()))
        else:
            chunks.append((text + "\n", (tag,)))
        self.append(self.chat, chunks)

    def console_write(self, markup_text, tag=None):
        chunks = []
        for chunk, color, bold in styled_runs(markup_text):
            tags = []
            if tag:
                tags.append(tag)
            if color:
                name = "c" + color.lstrip("#")
                if name not in self.color_tags:
                    self.console.tag_configure(name, foreground=color)
                    self.color_tags.add(name)
                tags.append(name)
            if bold:
                tags.append("bold")
            chunks.append((chunk, tuple(tags)))
        chunks.append(("\n", ()))
        self.append(self.console, chunks)

    def error(self, text):
        self.chat_log(text, "err")
        self.console_write(text.replace("[", "\\["), "err")

    # connection
    def connect_dialog(self):
        hash_hex = ConnectDialog(self).show()
        if hash_hex:
            self.connect_to(hash_hex)

    def connect_to(self, hash_hex):
        self.disconnect(quiet=True)
        name = self.servers.get(hash_hex, {}).get("name") or self.discovery.snapshot().get(hash_hex, {}).get("name")
        self.server_hash = hash_hex
        self.server_name = name or RNS.prettyhexrep(bytes.fromhex(hash_hex))
        self.client = Client(self.identity)
        self.started = False
        self.boards, self.messages, self.unread, self.rooms, self.reading = [], {}, {}, [], None
        self.chat_log(f"Connecting to {self.server_name}...")
        self.status_var.set(f"Connecting to {self.server_name}...")
        self.client.connect(hash_hex)
        self.rebuild_tree()

    def disconnect(self, quiet=False):
        client = self.client
        if client is None:
            return
        self.client = None
        client.disconnect()
        if not quiet:
            self.chat_log("Disconnected.")
        self.offline()

    def offline(self):
        self.status_var.set("Not connected")
        self.rtt_var.set("")
        self.where_var.set("")
        self.rns_label.configure(image=self.icons["rns_off"])
        self.tree.delete(*self.tree.get_children())
        self.set_connected_widgets(False)

    def set_connected_widgets(self, online):
        state = "!disabled" if online else "disabled"
        for button in self.online_buttons + [self.disconnect_button]:
            button.state([state])
        for entry in (self.chat_entry, self.console_entry):
            entry.state([state])

    def quit(self):
        try:
            self.settings["window"] = self.root.geometry()
            self.settings["sash"] = self.pane.sashpos(0)
            self.settings.save()
        except (tk.TclError, OSError):
            pass
        self.disconnect(quiet=True)
        self.root.destroy()

    # navigation
    def online(self):
        if self.client is None or not self.client.connected or self.client.area is None:
            self.chat_log("Not connected.", "err")
            return False
        return True

    def navigate(self, area, *commands, console=False):
        """Go to an area and run commands, warning first if that drops you out of a chat room."""
        if not self.online():
            return False
        client = self.client
        if client.room and area != CHAT and client.planned_area() == CHAT:
            if not messagebox.askyesno(
                APP_TITLE,
                f"RetiBBS takes you out of chat room '{client.room}' when you leave the chat area.\n\nContinue?",
                parent=self.root,
            ):
                return False
        client.goto(area, *commands)
        if console:
            self.notebook.select(2)
        return True

    def open_boards(self):
        self.navigate(BOARDS, "lb")

    def open_rooms(self):
        self.navigate(CHAT, "/list")

    def open_board(self, board, page_command="lm"):
        steps = []
        if self.client.board != board or self.client.planned_area() != BOARDS:
            steps.append((f"cb {board}", "board", board))
        steps += [page_command, "lu"]
        self.navigate(BOARDS, *steps)

    def read_message(self, board, message_id):
        steps = []
        if self.client.board != board:
            steps.append((f"cb {board}", "board", board))
        steps.append(f"r {message_id}")
        self.navigate(BOARDS, *steps)

    def join_room(self, room):
        self.navigate(CHAT, f"/j {room}", "/list")
        self.notebook.select(0)

    def leave_room(self):
        if self.client and self.client.room:
            self.navigate(CHAT, "/l", "/list")

    def refresh_view(self):
        if not self.online():
            return
        tab = self.notebook.index("current")
        if tab == 0 or self.client.area == CHAT:
            self.open_rooms()
        elif self.client.board:
            self.open_board(self.client.board)
        else:
            self.open_boards()

    def server_help(self):
        if self.online():
            self.client.run("/?" if self.client.planned_area() == CHAT else "?")
            self.notebook.select(2)

    def new_post(self, board=None):
        if not self.online():
            return
        result = PostDialog(self, self.boards, board or self.client.board).show()
        if result:
            board, command = result
            self.open_board_then(board, command)

    def open_board_then(self, board, command):
        steps = []
        if self.client.board != board:
            steps.append((f"cb {board}", "board", board))
        steps.append(command)
        self.navigate(BOARDS, *steps)

    def reply(self, message=None):
        if not self.online():
            return
        message = message or self.reading
        if message is None:
            messagebox.showinfo(APP_TITLE, "Open a message first (double click it in the board list).", parent=self.root)
            return
        result = PostDialog(self, self.boards, reply_to=message).show()
        if result:
            self.open_board_then(message["board"], result[1])

    def send_chat(self):
        text = self.chat_entry.get().strip()
        if not text or not self.online():
            return
        if text.startswith("/"):
            self.navigate(CHAT, text)
        elif not self.client.room:
            self.chat_log("Join a room first: double click one in the tree, or type /join NAME.", "err")
            return
        elif not self.client.fits(text):
            self.chat_log("That message is too long for one packet.", "err")
            return
        else:
            self.client.run(text)
        self.chat_entry.delete(0, "end")

    def send_console(self):
        text = self.console_entry.get().strip()
        if not text or not self.online():
            return
        self.console_write("> " + text.replace("[", "\\["), "sys")
        self.client.run(text)
        self.console_entry.delete(0, "end")

    # tree
    def rebuild_tree(self):
        tree = self.tree
        tree.delete(*tree.get_children())
        if self.client is None:
            return
        tree.insert("", "end", iid=ROOT_ID, text=" " + self.server_name, image=self.icons["server"], open=True)
        tree.insert(ROOT_ID, "end", iid=BOARDS_ID, text=" Message Boards", open=True)
        tree.insert(ROOT_ID, "end", iid=ROOMS_ID, text=" Chat Rooms", open=True)
        self.fill_boards()
        self.fill_rooms()

    def fill_boards(self):
        if not self.tree.exists(BOARDS_ID):
            return
        opened = {item for item in self.tree.get_children(BOARDS_ID) if self.tree.item(item, "open")}
        self.tree.delete(*self.tree.get_children(BOARDS_ID))
        current = self.client.board if self.client else None
        for board in self.boards:
            iid = "board:" + board
            unread = self.unread.get(board)
            label = f" {board}" + (f"  ({len(unread)} unread)" if unread else "")
            self.tree.insert(
                BOARDS_ID, "end", iid=iid, text=label, image=self.icons["channel"],
                tags=("self",) if board == current else (), open=iid in opened or board == current,
            )
            self.fill_messages(board)

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
            self.tree.insert(iid, "end", iid=f"empty:{board}", text="(no messages)")

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
            self.tree.insert(
                ROOMS_ID, "end", iid="room:" + name, text=f" {name}  ({count})",
                image=self.icons["user_idle"] if name == current else self.icons["channel"],
                tags=("self",) if name == current else (),
            )
        if not rooms:
            self.tree.insert(ROOMS_ID, "end", iid="rooms:none", text="(no open rooms; right click to create one)")

    def tree_open(self, event=None):
        selection = self.tree.selection()
        if not selection or not self.online():
            return "break"
        iid = selection[0]
        kind, _, rest = iid.partition(":")
        if iid == BOARDS_ID:
            self.open_boards()
        elif iid == ROOMS_ID or iid == "rooms:none":
            self.open_rooms()
        elif kind == "board":
            self.open_board(rest)
        elif kind == "msg":
            board, _, message_id = rest.rpartition(":")
            self.read_message(board, int(message_id))
        elif kind == "next":
            self.open_board_then(rest, ">")
        elif kind == "prev":
            self.open_board_then(rest, "<")
        elif kind == "room":
            if self.client.room == rest:
                self.notebook.select(0)
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
        if iid == BOARDS_ID:
            menu.add_command(label="Refresh", command=self.open_boards)
            menu.add_command(label="New post...", command=self.new_post)
            if admin:
                menu.add_command(label="New board...", command=self.new_board)
        elif kind == "board":
            menu.add_command(label="Open", command=lambda: self.open_board(rest))
            menu.add_command(label="New post...", command=lambda: self.new_post(rest))
            menu.add_separator()
            menu.add_command(label="Watch (LXMF alerts)", command=lambda: self.navigate(BOARDS, f"w {rest}", console=True))
            menu.add_command(label="Unwatch", command=lambda: self.navigate(BOARDS, f"uw {rest}", console=True))
            if admin:
                menu.add_separator()
                menu.add_command(label="Delete board...", command=lambda: self.delete_board(rest))
        elif kind == "msg":
            board, _, message_id = rest.rpartition(":")
            menu.add_command(label="Read", command=lambda: self.read_message(board, int(message_id)))
        elif iid in (ROOMS_ID, "rooms:none"):
            menu.add_command(label="Refresh", command=self.open_rooms)
            menu.add_command(label="Create or join room...", command=self.ask_room)
        elif kind == "room":
            if self.client.room == rest:
                menu.add_command(label="Leave", command=self.leave_room)
            else:
                menu.add_command(label="Join", command=lambda: self.join_room(rest))
        else:
            return
        self.palette_menu(menu)
        menu.tk_popup(event.x_root, event.y_root)

    def palette_menu(self, menu):
        palette = self.palette
        menu.configure(bg=palette["btn"], fg=palette["fg"])
        menu.configure(activebackground=palette["select"], activeforeground=palette["selfg"])

    def ask_name(self, title, prompt):
        dialog = Dialog(self.root, title)
        ttk.Label(dialog.body, text=prompt).grid(row=0, column=0, sticky="w")
        value = tk.StringVar()
        entry = ttk.Entry(dialog.body, textvariable=value, width=30)
        entry.grid(row=1, column=0, sticky="ew", pady=4)
        entry.focus_set()
        entry.bind("<Return>", lambda event: dialog.ok())
        dialog.buttons()
        original_ok = dialog.ok

        def ok():
            dialog.result = value.get().strip() or None
            original_ok()

        dialog.ok = ok
        return dialog.show()

    def ask_room(self):
        name = self.ask_name("Chat room", "Room name (a new room is created if it does not exist):")
        if name:
            self.join_room(name)

    def new_board(self):
        name = self.ask_name("New board", "Board name:")
        if name:
            self.navigate(BOARDS, f"nb {name}", "lb", console=True)

    def delete_board(self, board):
        if messagebox.askyesno(APP_TITLE, f"Delete board '{board}' and all its messages?", parent=self.root):
            self.navigate(BOARDS, f"db {board}", "lb", console=True)

    # reader
    def show_message(self, message):
        message["board"] = self.client.board
        self.reading = message
        reader = self.reader
        reader.configure(state="normal")
        reader.delete("1.0", "end")
        reader.insert("end", message["topic"] + "\n", ("title",))
        meta = f"{message['author']}  ·  {message['time']}  ·  #{message['id']}  in {message['board']}"
        reader.insert("end", meta + "\n\n", ("meta",))
        reader.insert("end", message["body"] + "\n")
        if message["replies"]:
            count = len(message["replies"])
            reader.insert("end", f"\n{count} {'reply' if count == 1 else 'replies'}\n", ("bold",))
            for reply in message["replies"]:
                reader.insert("end", f"\n{reply['author']}", ("name",))
                reader.insert("end", f"  {reply['time']}\n", ("meta",))
                reader.insert("end", reply["body"] + "\n")
        reader.configure(state="disabled")
        self.reader_title.configure(text=f"{message['board']} › {message['topic']}")
        self.notebook.select(1)
        self.unread.get(message["board"], set()).discard(message["id"])
        self.fill_boards()

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
        """Use the announced name once an announce arrives."""
        name = self.discovery.snapshot().get(self.server_hash, {}).get("name")
        if not name or name == self.server_name:
            return
        self.server_name = name
        if self.server_hash in self.servers:
            self.servers[self.server_hash]["name"] = name
            self.servers.save()
        if self.tree.exists(ROOT_ID):
            self.tree.item(ROOT_ID, text=" " + name)
        if self.client.connected:
            self.update_where()

    def update_where(self):
        client = self.client
        if client is None:
            return
        who = client.user_name or RNS.prettyhexrep(self.identity.hash)
        admin = " (admin)" if client.is_admin else ""
        self.status_var.set(f"Connected to {self.server_name} as {who}{admin}")
        parts = [client.area or ""]
        if client.area == BOARDS and client.board:
            parts.append(client.board)
        if client.area == CHAT and client.room:
            parts.append(client.room)
        self.where_var.set(" › ".join(part for part in parts if part))

    def handle_event(self, event):
        kind = event[0]
        client = self.client
        if kind == "status":
            self.status_var.set(event[1])
            self.chat_log(event[1])
        elif kind == "failed":
            self.error(event[1])
            self.client = None
            self.offline()
        elif kind == "connected":
            hops = event[1]
            path = f" ({hops} hop{'s' if hops != 1 else ''} away)" if hops is not None else ""
            self.chat_log(f"Connected to {self.server_name}{path}.")
            self.rns_label.configure(image=self.icons["rns_online"])
            self.set_connected_widgets(True)
            self.update_where()
        elif kind == "disconnected":
            self.error(f"Connection {event[1]}.")
            self.client = None
            self.offline()
        elif kind == "area":
            if not self.started:
                self.started = True
                # the server cannot answer "h" until the user has a name
                if self.settings["display_name"]:
                    client.run(f"n {self.settings['display_name']}")
                client.run("h")
                client.goto(CHAT, "/list")
                client.goto(BOARDS, "lb")
            self.update_where()
        elif kind == "board":
            self.update_where()
            self.fill_boards()
        elif kind in ("room", "joined", "left"):
            if kind == "left" and event[1]:
                self.chat_log(f"You left {event[1]}.")
            self.update_where()
            self.fill_rooms()
        elif kind == "hello":
            self.update_where()
        elif kind == "named":
            client.user_name = self.settings["display_name"] or client.user_name
            self.update_where()
        elif kind == "boards":
            self.boards = event[1]
            self.fill_boards()
        elif kind == "messages":
            _, board, page, pages, messages = event
            self.messages[board] = (page, pages, messages)
            self.fill_boards()
            item = "board:" + board
            if self.tree.exists(item):
                self.tree.item(item, open=True)
        elif kind == "unread":
            self.unread[event[1]] = set(event[2])
            self.fill_boards()
        elif kind == "message":
            self.show_message(event[1])
        elif kind == "posted":
            board = client.board
            if self.reading and self.reading.get("board") == board:
                client.run(f"r {self.reading['id']}")
            client.run("lm", "lu")
        elif kind == "rooms":
            self.rooms = event[1]
            self.fill_rooms()
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
            self.console.configure(state="normal")
            self.console.delete("1.0", "end")
            self.console.configure(state="disabled")
        elif kind == "rtt":
            self.rtt_var.set(f"RTT {event[1]:.2f} s")
        elif kind == "error":
            self.error(event[1])

    def about(self):
        messagebox.showinfo(
            APP_TITLE,
            "A desktop client for RetiBBS (github.com/kc1awv/RetiBBS).\n\n"
            "Look and layout from partyline (github.com/RFnexus/partyline).\n"
            f"Your identity: {RNS.prettyhexrep(self.identity.hash)}",
            parent=self.root,
        )


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
        root.after(200, lambda: app.connect_to(args.server.strip("<>").lower()))
    root.mainloop()
    RNS.exit()


if __name__ == "__main__":
    main()
