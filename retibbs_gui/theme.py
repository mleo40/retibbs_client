"""Colors and ttk styling.

The palettes and style rules are taken from partyline (public domain,
https://github.com/RFnexus/partyline) so the two apps look alike.
"""

import tkinter as tk
from tkinter import ttk

PALETTES = {
    "light": {
        "bg": "#f0f0f0",
        "fg": "#000000",
        "field": "#ffffff",
        "btn": "#e4e4e4",
        "btn_active": "#d4d4d4",
        "border": "#c4c4c4",
        "select": "#4c8bd6",
        "selfg": "#ffffff",
        "muted": "#777777",
        "sys": "#3b6ea5",
        "err": "#c0392b",
        "me": "#2e7d32",
    },
    "dark": {
        "bg": "#2b2b2b",
        "fg": "#e6e6e6",
        "field": "#1e1e1e",
        "btn": "#3c3c3c",
        "btn_active": "#4a4a4a",
        "border": "#4a4a4a",
        "select": "#3d6fb4",
        "selfg": "#ffffff",
        "muted": "#9a9a9a",
        "sys": "#7fb0ea",
        "err": "#ef7b73",
        "me": "#7bc67e",
    },
}


def apply_theme(root, palette, menus=(), texts=()):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        ".",
        background=palette["bg"],
        foreground=palette["fg"],
        fieldbackground=palette["field"],
        bordercolor=palette["border"],
        lightcolor=palette["bg"],
        darkcolor=palette["bg"],
        troughcolor=palette["field"],
        selectbackground=palette["select"],
        selectforeground=palette["selfg"],
        insertcolor=palette["fg"],
        arrowcolor=palette["fg"],
    )
    style.configure("TButton", background=palette["btn"])
    style.map(
        "TButton",
        background=[("active", palette["btn_active"]), ("disabled", palette["bg"])],
        foreground=[("disabled", palette["muted"])],
    )
    style.configure("Toolbutton", background=palette["bg"])
    style.map(
        "Toolbutton",
        background=[("selected", palette["select"]), ("active", palette["btn_active"])],
        foreground=[("selected", palette["selfg"])],
    )
    style.configure("Treeview", background=palette["field"], fieldbackground=palette["field"], foreground=palette["fg"])
    style.map("Treeview", background=[("selected", palette["select"])], foreground=[("selected", palette["selfg"])])
    style.configure("Treeview.Heading", background=palette["btn"], foreground=palette["fg"])
    style.map("Treeview.Heading", background=[("active", palette["btn_active"])])
    style.configure("TNotebook.Tab", background=palette["btn"], foreground=palette["fg"])
    style.map("TNotebook.Tab", background=[("selected", palette["bg"])])
    style.configure("TEntry", fieldbackground=palette["field"], foreground=palette["fg"])
    style.configure("TCombobox", fieldbackground=palette["field"], foreground=palette["fg"], background=palette["btn"])
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", palette["field"])],
        foreground=[("readonly", palette["fg"])],
        selectbackground=[("readonly", palette["field"])],
        selectforeground=[("readonly", palette["fg"])],
    )
    for widget_class in ("TCheckbutton", "TRadiobutton"):
        style.configure(
            widget_class,
            indicatorsize=16,
            indicatormargin=(2, 2, 6, 2),
            indicatorbackground=palette["field"],
            indicatorforeground=palette["fg"],
            upperbordercolor=palette["border"],
            lowerbordercolor=palette["border"],
        )
        style.map(
            widget_class,
            background=[("active", palette["bg"])],
            indicatorbackground=[("selected", palette["select"]), ("pressed", palette["btn_active"])],
            indicatorforeground=[("selected", palette["selfg"])],
            upperbordercolor=[("selected", palette["select"])],
            lowerbordercolor=[("selected", palette["select"])],
        )
    style.configure("TProgressbar", background=palette["select"], troughcolor=palette["field"])
    style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["fg"])
    style.configure("TScrollbar", background=palette["btn"], troughcolor=palette["bg"], arrowcolor=palette["fg"])

    root.configure(bg=palette["bg"])
    for option, value in (
        ("*background", palette["bg"]),
        ("*foreground", palette["fg"]),
        ("*Menu.background", palette["btn"]),
        ("*Menu.foreground", palette["fg"]),
        ("*Menu.activeBackground", palette["select"]),
        ("*Menu.activeForeground", palette["selfg"]),
        ("*Entry.background", palette["field"]),
        ("*Entry.foreground", palette["fg"]),
        ("*Entry.insertBackground", palette["fg"]),
        ("*Text.background", palette["field"]),
        ("*Listbox.background", palette["field"]),
        ("*Listbox.foreground", palette["fg"]),
        ("*TCombobox*Listbox.background", palette["field"]),
        ("*TCombobox*Listbox.foreground", palette["fg"]),
        ("*TCombobox*Listbox.selectBackground", palette["select"]),
    ):
        root.option_add(option, value)

    for menu in menus:
        menu.configure(
            bg=palette["btn"],
            fg=palette["fg"],
            activebackground=palette["select"],
            activeforeground=palette["selfg"],
            borderwidth=0,
        )
    for text in texts:
        text.configure(
            bg=palette["field"],
            fg=palette["fg"],
            insertbackground=palette["fg"],
            selectbackground=palette["select"],
            selectforeground=palette["selfg"],
            highlightthickness=0,
        )
        for tag in ("sys", "err", "me"):
            text.tag_configure(tag, foreground=palette[tag])
        text.tag_configure("time", foreground=palette["muted"])
