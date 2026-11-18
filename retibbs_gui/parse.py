"""Turn RetiBBS server text into structured events.

RetiBBS replies with text written for people, plus a few CTRL packets.
These functions recognise the replies the GUI needs (board list, message
list, a read message, room list, chat lines) by their wording. Anything
not recognised is shown as plain text in the console tab.
"""

import re

try:
    from rich.errors import MarkupError
    from rich.style import Style
    from rich.text import Text
except ImportError:  # rich is optional; without it markup is stripped
    Text = None

MARKUP_TAG = re.compile(r"(?<!\\)\[/?[a-zA-Z#][^\[\]]*\]|(?<!\\)\[/\]")

TS = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d"
MSG_HEADER = re.compile(r"^Messages in board '(.+)' \(Page (\d+)/(\d+)\):")
MSG_LINE = re.compile(rf"^\[(\d+)\] ({TS}) \| (.*?) \| (.*) \((\d+) repl(?:y|ies)\)$")
UNREAD_HEADER = re.compile(r"^Unread messages in board '(.+)':")
UNREAD_LINE = re.compile(rf"^\[(\d+)\] ({TS}) \| (.*?) \| (.*)$")
NO_MSGS = re.compile(r"^No (?:unread )?messages (?:found )?in board '(.+)'\.")
READ_HEADER = re.compile(r"-{5} Message (\d+) -{5}")
REPLY_LINE = re.compile(rf"^\s+\[(\d+)\] ({TS}) \| (.*?): (.*)$")
ROOM_LINE = re.compile(r"^\s+- (.+) \((\d+) participants?\)$")
CHAT_MINE = re.compile(r"^\[(.+?)\] \(You\): (.*)$", re.S)
CHAT_OTHER = re.compile(r"^\[(.+?)\] ([^:\n]+?): (.*)$", re.S)
CHAT_NOTICE = re.compile(r"^\[(.+?)\] (.+)$", re.S)
HELLO = re.compile(r"^Hello, (.+?)\.$", re.M)


def unescape(text):
    return text.replace("\\[", "[")


def plain(text):
    """Text without Rich markup."""
    if Text is not None:
        try:
            return Text.from_markup(text).plain
        except MarkupError:
            return text
    return unescape(MARKUP_TAG.sub("", text))


def styled_runs(text):
    """Split text into (chunk, color or None, bold) runs for the Tk text widget."""
    if Text is None:
        return [(plain(text), None, False)]
    try:
        rich_text = Text.from_markup(text)
    except MarkupError:
        return [(text, None, False)]
    body = rich_text.plain
    marks = {0, len(body)}
    for span in rich_text.spans:
        marks.update((span.start, span.end))
    edges = sorted(mark for mark in marks if 0 <= mark <= len(body))
    runs = []
    for start, end in zip(edges, edges[1:]):
        color, bold = None, False
        for span in rich_text.spans:
            if span.start <= start and span.end >= end:
                style = span.style if isinstance(span.style, Style) else Style.parse(str(span.style))
                if style.color is not None and not style.color.is_default:
                    color = style.color.get_truecolor().hex
                bold = bold or bool(style.bold)
        runs.append((body[start:end], color, bold))
    return runs


def classify(text, area=None, room=None):
    """Return a list of events for one server reply.

    Each event is a tuple whose first item names it. A reply that is
    shown in the console gets a ("text", raw) event as well.
    """
    body = plain(text).strip("\n")
    first = body.split("\n", 1)[0].strip()
    lines = body.split("\n")

    if first == "All Boards:":
        return [("boards", [line.strip() for line in lines[1:] if line.strip()])]
    if first == "No boards exist.":
        return [("boards", [])]

    match = MSG_HEADER.match(first)
    if match:
        messages = []
        for line in lines[1:]:
            m = MSG_LINE.match(line.strip())
            if m:
                messages.append(
                    {"id": int(m[1]), "time": m[2], "author": m[3], "topic": m[4], "replies": int(m[5]), "unread": False}
                )
        return [("messages", match[1], int(match[2]), int(match[3]), messages)]
    match = UNREAD_HEADER.match(first)
    if match:
        unread = []
        for line in lines[1:]:
            m = UNREAD_LINE.match(line.strip())
            if m:
                unread.append(int(m[1]))
        return [("unread", match[1], unread)]
    match = NO_MSGS.match(first)
    if match:
        if "unread" in first:
            return [("unread", match[1], [])]
        return [("messages", match[1], 1, 1, [])]

    match = READ_HEADER.search(body)
    if match:
        return [("message", parse_message(int(match[1]), body[match.end():]))]

    if first == "Available Chat Rooms:":
        rooms = []
        for line in lines[1:]:
            m = ROOM_LINE.match(line)
            if m:
                rooms.append((m[1], int(m[2])))
        return [("rooms", rooms)]
    if first.startswith("No chat rooms are currently open"):
        return [("rooms", [])]

    if first.startswith("Joined room: "):
        return [("joined", first[len("Joined room: "):].strip())]
    if first.startswith("Left room: "):
        return [("left", first[len("Left room: "):].strip())]
    if first.startswith("Posted to board '") or first.startswith("Reply posted to message ID"):
        return [("posted",), ("text", text)]
    if first.startswith("Your display name is now set to"):
        return [("text", text), ("named",)]

    # Chat lines start with an unescaped "[room]", which Rich would read as a tag, so match the raw text
    if area == "Chat" and "\n" not in text.strip():
        line = unescape(text.strip())
        m = CHAT_MINE.match(line)
        if m:
            return [("chat", m[1], None, m[2], True)]
        m = CHAT_OTHER.match(line)
        if m and (room is None or m[1] == room):
            return [("chat", m[1], m[2], m[3], False)]
        m = CHAT_NOTICE.match(line)
        if m and (room is None or m[1] == room):
            return [("chat", m[1], None, m[2], False)]

    events = []
    hello = HELLO.search(body)
    if hello:
        events.append(("hello", hello[1], "ADMIN rights" in body))
    events.append(("text", text))
    return events


def parse_message(message_id, rest):
    fields = {"id": message_id, "time": "", "author": "", "topic": "", "body": "", "replies": []}
    head, _, after = rest.lstrip("\n").partition("\n\n")
    for line in head.split("\n"):
        key, _, value = line.partition(": ")
        if key in ("Timestamp", "Author", "Topic"):
            fields[{"Timestamp": "time", "Author": "author", "Topic": "topic"}[key]] = value
    after = after.split("\nTo reply, use:", 1)[0]
    content, _, reply_block = after.partition("\nReplies:\n")
    fields["body"] = content.strip("\n")
    for line in reply_block.split("\n"):
        m = REPLY_LINE.match(line)
        if m:
            fields["replies"].append({"id": int(m[1]), "time": m[2], "author": m[3], "body": m[4]})
    return fields
