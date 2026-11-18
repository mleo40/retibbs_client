# retibbs_client

A desktop client for [RetiBBS](https://github.com/kc1awv/RetiBBS), the bulletin board system for Reticulum networks.
It uses the look and layout of [partyline](https://github.com/RFnexus/partyline), with light and dark themes.

RetiBBS ships with a terminal (Textual) client where you type menu commands. This client turns the boards, messages,
chat rooms and users into a clickable list, opens messages in a reader, gives you post and reply dialogs, and shows
the server's limits where they apply.

Reading a message (light theme):

![Reading a message in the light theme](docs/message_light.png)

Chatting in a room, as an admin with the user list loaded (dark theme):

![Chatting in a room in the dark theme](docs/chat_dark.png)

Writing a post that is too long for one packet, with the limit of a LoRa link:

![The post dialog over its size limit](docs/post_dialog.png)

Settings, with the address for board alerts:

![The settings dialog](docs/settings_dialog.png)

## Layout

- Toolbar: the connection only. Connect, Disconnect, the BBS name and who you are signed in as, and Settings.
- Right: everything on the BBS. Message boards and their messages, chat rooms, and Users for admins. Double click
  to open, right click for more.
- Left: three tabs, each with its own buttons in its header.
  - Chat: the room you are in, with Leave room and a counter for the message size.
  - Message: the post you opened, with Reply and New post.
  - Server log: everything the server sends. Type any RetiBBS command here.
- A strip under the toolbar shows the server's answers: errors in red, confirmations in blue.
- Status bar: connection, board alerts on or off, and round trip time.

## Features

- Boards with new message counts, paging, and a reader for messages and their replies
- New post and reply dialogs that count bytes against the packet limit of your connection
- Chat rooms: join, leave, start one, with a size counter on every message
- Board alerts: set your LXMF address in Settings, send a test, and turn alerts on per board
- Admins: list users, make admins, create and delete boards
- Your own name for each BBS, kept when the server announces a different one
- Asks for a display name on first connect, since RetiBBS needs one before it answers

## Server limits

These come from the RetiBBS server, not from this client. The client marks them with a yellow Server limit note where
they apply, and lists them under Help > Server limits.

- Posts and replies must fit in one Reticulum packet, topic included. The size depends on the slowest link to the
  server: a few hundred bytes over LoRa or packet radio, far more over TCP or a local network.
- Posts cannot be edited or deleted. Only admins can delete a board, with all its messages.
- Chat is live only and not stored. You see only what is said while you are in the room.
- You stay in a room only while you are in the chat area. Opening the boards, changing your name or alert address,
  or listing users takes you out of the room. The client asks first.
- Each chat message must also fit in one packet, together with the room and your name.
- No file sharing.
- Board alerts go to another LXMF app, such as Sideband, Columba, MeshChat or NomadNet. This client cannot receive
  them. An alert address can be replaced but not removed; turn alerts off per board instead.
- Each BBS allows a display name only once. Board names are 3 to 20 letters or digits.
- RetiBBS has no command to take admin rights away.

## How it works

RetiBBS servers reply with text meant for people plus a few control packets (`CTRL AREA`, `CTRL BOARD`,
`CTRL ROOM`). The client recognises the replies it needs by their wording and shows everything in the Server log. It
also moves between the server's areas for you: opening a board sends `b`, `cb <board>`, `lm`; joining a room sends
`/b`, `c`, `/j <room>`.

## Compatibility

- Python 3.10 or newer, Linux, macOS or Windows
- Tested against the RetiBBS server at commit `7c26d2c` (January 2026)
- Uses the same identity file as the RetiBBS Textual client, so you keep your account and admin rights

## Requirements

- [Reticulum](https://reticulum.network/) (`rns`) with a working configuration
- [Rich](https://github.com/Textualize/rich) for colors in server menus
- Tk for Python, which pip cannot install. On Debian or Ubuntu: `sudo apt install python3-tk`. On Fedora:
  `sudo dnf install python3-tkinter`

## Reticulum

The client does not need its own rnsd service. When it starts, it looks for a shared Reticulum instance:

- If one is running (`rnsd`, or another app with sharing on, such as MeshChat, Sideband or NomadNet), the client
  attaches to it and uses its interfaces.
- If none is running, the client starts Reticulum itself from `~/.reticulum/config`, or the folder given with
  `--reticulum-config`. While the client is open, other Reticulum apps attach to it.

If the client started Reticulum, closing it takes the network down for every app attached to it. If you run several
Reticulum apps, or want the machine always reachable, run `rnsd` as a service and let the apps attach to it.

## Recommended server setup

If you run a RetiBBS server, these settings suit this client. None of them need changes to the server code.

`server_config.json`:

```json
{
    "server_name": "Club BBS",
    "announce_interval": 600,
    "theme": "radio",
    "enable_web_server": false,
    "use_wsgi": false
}
```

- `server_name`: shown in the client's list of BBSes heard on the network. Keep it short.
- `announce_interval`: the client finds servers from their announces. If this is missing or 0, the server does not
  announce on a schedule and users need its address. Use about 600 seconds on mixed networks, 1800 on LoRa only
  networks to save airtime, and 300 on TCP.
- `enable_web_server`: off. The client does not use the read only web page.

A light theme. The server resends its header and a menu every time the client moves between areas, which the
default theme makes about 2 KB each time; opening a board from a chat room is two moves. The client shows these
menus only in the Server log, so one line each is enough. Create `themes/radio/` in the server folder with:

| File | Contents |
|---|---|
| `header.txt` | `Club BBS` |
| `welcome_message.txt` | `Welcome to Club BBS. Set a display name with: n <name>` |
| `main_menu.txt` | `Main menu. ? for help.` |
| `boards_menu.txt` | `Message boards. ? for help.` |
| `chat_menu.txt` | `Chat. /? for help.` |

The server reads `themes`, its databases and `lxmf_storage` from the folder it starts in, so start it from the
server folder. The theme is always taken from `server_config.json` in that folder; `--config-file` only changes the
name, announces and web server.

The first admin. RetiBBS has no command for this, so set it once in the server's user database:

1. Connect once with this client, so the server creates your account.
2. Settings > Your BBS identity > Copy.
3. Run the command below in the server folder with your identity pasted in. The server reads the database on every
   command, so no restart is needed. In the client, BBS > Check my account picks up the change.

```bash
sqlite3 users.db "UPDATE users SET is_admin=1 WHERE hash_hex='PASTE_IDENTITY_HERE';"
```

After that, create the boards from the client (right click Message boards > New board) and make other admins from
the user list. Members cannot post until at least one board exists.

Start the server against a shared `rnsd`, so the BBS and its board alerts use the same interfaces:

```bash
cd RetiBBS/server && python retibbs_server.py --config-file server_config.json --identity-file server_identity.pem
```

The server prints its address at start, labelled "Identity hash". That is the address clients connect to.

Running unattended. The server waits for keyboard input (Enter sends an announce) and exits when that input closes,
so it stops at once under `nohup` or a service manager. Run it in `tmux` or `screen`, or keep its input open:

```bash
tail -f /dev/null | python retibbs_server.py
```

Reaching the server on a LAN. Reticulum finds machines on the local network by IPv6 multicast, which many Wi-Fi
networks and firewalls block; the log then says "No multicast echoes received". Link the machines over TCP instead.
On the server, add to `~/.reticulum/config` under `[interfaces]` and open TCP port 4242:

```
  [[LAN TCP]]
    type = TCPServerInterface
    enabled = yes
    listen_ip = 0.0.0.0
    listen_port = 4242
```

On each client machine, with the server's IP address:

```
  [[BBS server]]
    type = TCPClientInterface
    enabled = yes
    target_host = 192.168.1.20
    target_port = 4242
```

Board alerts are sent directly, never through a propagation node. If the member's LXMF app is offline when a post
arrives, the alert is lost after a few retries. Members who want alerts should keep that app running and reachable.

Back up `server_identity.pem` (the BBS address; a new one means a new address), `users.db`, `boards.db` and
`lxmf_storage/`.

## Install

```bash
git clone https://github.com/mleo40/retibbs_client.git
cd retibbs_client
python3 -m venv .venv
.venv/bin/pip install .
```

## Usage

Start the client:

```bash
.venv/bin/retibbs-gui
```

Connect straight to a server:

```bash
.venv/bin/retibbs-gui --server b40428672a09c6c100ca82c10e5d945f
```

Use another Reticulum configuration:

```bash
.venv/bin/retibbs-gui --reticulum-config ~/.reticulum-test
```

First steps in the window:

1. Connect... lists your saved BBSes and the ones heard on the network. Pick one or paste its address. Type a Name
   if you want your own name for it, then Connect.
2. On the first connection, pick a display name.
3. Double click a board to list its messages; new ones are bold. Double click a message to read it.
4. Double click a chat room to join it, or right click Chat rooms to start one.

More:

- Board alerts: Settings > Board alerts, paste the LXMF address of your phone or other LXMF app, Send test. Then
  right click a board and tick Alert me about new posts.
- Rename a BBS: right click its name at the top of the list, or Server > Rename this BBS.
- Commands typed in the Chat box that start with `/` go to the server's chat area, for example `/list`.
- Admins: double click Users to load them; right click a user to make them an admin. Right click Message boards for
  New board, or a board for Delete board.
- Keys: Ctrl+O connect, Ctrl+N new post, F5 refresh, Ctrl+1, 2 and 3 for the tabs.

Settings and saved servers live in `~/.config/retibbs-gui/`.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

## Credits

- Theme, palettes and layout adapted from partyline (public domain)
- Icons from [Tabler Icons](https://tabler.io/icons) (MIT), see `retibbs_gui/icons/LICENSE`

## Revision history

- 0.2.0: Clearer layout with per tab buttons, server limits marked, board alerts, user list for admins, own names
  for each BBS, fix for the OK button in name prompts
- 0.1.0: First prototype
