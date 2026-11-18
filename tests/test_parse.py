import unittest

from retibbs_gui.parse import classify, plain, styled_runs


class ParseTests(unittest.TestCase):
    def test_board_list(self):
        self.assertEqual(classify("All Boards:\ngeneral\nradio\n"), [("boards", ["general", "radio"])])
        self.assertEqual(classify("No boards exist."), [("boards", [])])

    def test_message_list(self):
        text = (
            "Messages in board 'general' (Page 1/2):\n"
            "[12] 2025-01-01 13:31:08 | Mike | Net tonight (3 replies)\n"
            "[11] 2025-01-01 10:00:00 | a | b | c (1 replies)\n"
            "\nCommands: 'r <id>' to read a message, < (prev) || > (next) for navigation."
        )
        [(kind, board, page, pages, messages)] = classify(text)
        self.assertEqual((kind, board, page, pages), ("messages", "general", 1, 2))
        self.assertEqual(messages[0]["id"], 12)
        self.assertEqual(messages[0]["topic"], "Net tonight")
        self.assertEqual(messages[0]["replies"], 3)
        self.assertEqual(messages[1]["author"], "a")

    def test_empty_and_unread(self):
        self.assertEqual(classify("No messages found in board 'x'."), [("messages", "x", 1, 1, [])])
        self.assertEqual(classify("No unread messages in board 'x'."), [("unread", "x", [])])
        text = "Unread messages in board 'x':\n[4] 2025-01-01 13:31:08 | Mike | Hi"
        self.assertEqual(classify(text), [("unread", "x", [4])])

    def test_read_message(self):
        text = (
            "\n[bold]----- Message 12 -----[/]\nTimestamp: 2025-01-01 13:31:08\nAuthor: Mike\nTopic: Net\n\n"
            "Line one\nLine two\n\nReplies:\n  [13] 2025-01-02 09:00:00 | Ann: Count me in\n"
            "\nTo reply, use: reply <message_id> | <content>"
        )
        [(kind, message)] = classify(text)
        self.assertEqual(kind, "message")
        self.assertEqual(message["id"], 12)
        self.assertEqual(message["author"], "Mike")
        self.assertEqual(message["body"], "Line one\nLine two")
        self.assertEqual(message["replies"][0]["body"], "Count me in")

    def test_rooms(self):
        text = "Available Chat Rooms:\n  - lobby (2 participants)\n  - net (1 participant)\n"
        self.assertEqual(classify(text), [("rooms", [("lobby", 2), ("net", 1)])])
        self.assertEqual(classify("No chat rooms are currently open.\n\n /join x"), [("rooms", [])])

    def test_chat_lines(self):
        self.assertEqual(classify("[lobby] (You): hi", "Chat", "lobby"), [("chat", "lobby", None, "hi", True)])
        self.assertEqual(classify("[lobby] Ann: hello", "Chat", "lobby"), [("chat", "lobby", "Ann", "hello", False)])
        notice = classify("[lobby] Ann has joined the room.", "Chat", "lobby")
        self.assertEqual(notice, [("chat", "lobby", None, "Ann has joined the room.", False)])
        self.assertEqual(classify("Joined room: lobby", "Chat"), [("joined", "lobby")])
        self.assertEqual(classify("[lobby] Ann: hello", "Main Menu")[0][0], "text")

    def test_hello_and_markup(self):
        events = classify("Hello, Mike.\nYou have ADMIN rights.")
        self.assertEqual(events[0], ("hello", "Mike", True))
        self.assertEqual(plain("[bold red]Hi[/] \\[x]"), "Hi [x]")
        runs = styled_runs("[bold red]Hi[/] there")
        self.assertEqual(runs[0][0], "Hi")
        self.assertTrue(runs[0][2])
        self.assertIsNotNone(runs[0][1])


if __name__ == "__main__":
    unittest.main()
