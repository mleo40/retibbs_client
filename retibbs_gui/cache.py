"""Offline copy of a BBS: its boards, message lists and the messages you opened, as JSON per server.

RetiBBS never edits or deletes a single post, and message numbers are never reused on a server, so a cached message
stays valid until its board is deleted. Replies are the only thing that changes, and the message list shows their
count.
"""

import json
import os
import shutil

from .prefs import CONFIG_DIR

CACHE_DIR = os.path.join(CONFIG_DIR, "cache")


class ServerCache:
    def __init__(self, hash_hex, directory=CACHE_DIR):
        self.path = os.path.join(directory, hash_hex + ".json")
        self.data = {"updated": "", "welcome": "", "boards": [], "lists": {}, "messages": {}, "archived": []}
        try:
            with open(self.path, encoding="utf-8") as handle:
                self.data.update(json.load(handle))
        except (OSError, ValueError):
            pass

    def exists(self):
        return os.path.isfile(self.path)

    def save(self, now):
        """Write the copy, stamped with the time it was last brought up to date."""
        self.data["updated"] = now
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle)
        os.replace(temporary, self.path)

    @property
    def updated(self):
        return self.data["updated"]

    @property
    def boards(self):
        return self.data["boards"]

    @property
    def archived(self):
        """Boards deleted on the server and kept here: [{"name", "deleted", "list"}]."""
        return self.data["archived"]

    @property
    def welcome(self):
        return self.data["welcome"]

    @welcome.setter
    def welcome(self, text):
        self.data["welcome"] = text

    def board_list(self, board):
        """Cached message summaries of a board, newest first."""
        return self.data["lists"].get(board, [])

    def message(self, message_id):
        return self.data["messages"].get(str(message_id))

    def set_boards(self, boards, keep_deleted, today):
        """Take the server's board list; boards no longer on it are archived or dropped."""
        for board in list(self.data["lists"]):
            if board not in boards:
                self.retire(board, keep_deleted, today)
        self.data["boards"] = list(boards)

    def set_page(self, board, page, pages, messages, keep_deleted, today):
        """Take one page of a board's message list (newest first) and merge it into the cached list.

        A cached message that should be on this page but is not means the board was deleted and made again under
        the same name: the old messages are archived or dropped first.
        """
        listed = {message["id"] for message in messages}
        cached = [message["id"] for message in self.board_list(board)]
        if cached:
            high = max(listed) if listed else 0
            low = min(listed) if listed and pages > 1 else 0
            newer = page == 1 and max(cached) > high
            missing = any(low <= message_id <= high and message_id not in listed for message_id in cached)
            if newer or missing or (page == 1 and not listed):
                self.retire(board, keep_deleted, today)
        merged = {message["id"]: message for message in self.board_list(board)}
        for message in messages:
            summary = {key: message[key] for key in ("id", "time", "author", "topic", "replies")}
            merged[message["id"]] = summary
        self.data["lists"][board] = sorted(merged.values(), key=lambda message: message["id"], reverse=True)

    def put_message(self, board, message):
        """Keep an opened message with its replies."""
        stored = {key: message[key] for key in ("id", "time", "author", "topic", "body", "replies")}
        stored["board"] = board
        self.data["messages"][str(message["id"])] = stored

    def fresh_message(self, message_id, replies):
        """The cached message if it has the given number of replies, or None when it must be fetched."""
        message = self.message(message_id)
        if message is None or len(message["replies"]) != replies:
            return None
        return message

    def retire(self, board, keep_deleted, today):
        """Move a board's cached messages to the archive, or drop them."""
        summaries = self.data["lists"].pop(board, [])
        if keep_deleted and summaries:
            self.data["archived"].append({"name": board, "deleted": today, "list": summaries})
            return
        for summary in summaries:
            self.data["messages"].pop(str(summary["id"]), None)

    def remove_archived(self, index):
        """Drop an archived board and its messages."""
        for summary in self.data["archived"].pop(index)["list"]:
            self.data["messages"].pop(str(summary["id"]), None)

    def delete(self):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass


def delete_all(directory=CACHE_DIR):
    """Remove the offline copies of every BBS."""
    shutil.rmtree(directory, ignore_errors=True)


def has_any(directory=CACHE_DIR):
    return os.path.isdir(directory) and any(name.endswith(".json") for name in os.listdir(directory))


def usage(directory=CACHE_DIR):
    """Disk space taken by the offline copies: (bytes, number of BBSes)."""
    if not os.path.isdir(directory):
        return 0, 0
    sizes = [entry.stat().st_size for entry in os.scandir(directory) if entry.name.endswith(".json")]
    return sum(sizes), len(sizes)


def describe_usage(directory=CACHE_DIR):
    """Usage as text for people, such as "412 KB for 2 BBSes"."""
    size, count = usage(directory)
    if not count:
        return "No offline copies on this computer."
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            break
        size /= 1024
    amount = f"{size:.0f} {unit}" if unit in ("bytes", "KB") else f"{size:.1f} {unit}"
    return f"Offline copies use {amount} for {count} BBS{'es' if count != 1 else ''}."
