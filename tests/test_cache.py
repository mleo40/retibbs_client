import tempfile
import unittest

from retibbs_gui import cache

TODAY = "2026-11-18"


def summary(message_id, replies=0):
    return {"id": message_id, "time": "2026-11-18 10:00:00", "author": "mike", "topic": f"t{message_id}",
            "replies": replies, "unread": False}


def full(message_id, replies=0):
    return {"id": message_id, "time": "2026-11-18 10:00:00", "author": "mike", "topic": f"t{message_id}",
            "body": f"body {message_id}", "replies": [{"id": 100 + n} for n in range(replies)]}


class ServerCacheTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.cache = cache.ServerCache("ab" * 16, self.directory)

    def ids(self, board):
        return [message["id"] for message in self.cache.board_list(board)]

    def test_save_and_load(self):
        self.cache.set_page("general", 1, 1, [summary(2), summary(1)], False, TODAY)
        self.cache.put_message("general", full(2))
        self.cache.welcome = "Hi"
        self.cache.save("2026-11-18 10:05")
        loaded = cache.ServerCache("ab" * 16, self.directory)
        self.assertEqual([2, 1], [message["id"] for message in loaded.board_list("general")])
        self.assertEqual("general", loaded.message(2)["board"])
        self.assertEqual("Hi", loaded.welcome)
        self.assertEqual("2026-11-18 10:05", loaded.updated)
        self.assertTrue(cache.has_any(self.directory))

    def test_pages_merge(self):
        self.cache.set_page("general", 1, 2, [summary(9), summary(8)], False, TODAY)
        self.cache.set_page("general", 2, 2, [summary(5), summary(4)], False, TODAY)
        self.cache.set_page("general", 1, 2, [summary(10), summary(9)], False, TODAY)
        self.assertEqual([10, 9, 8, 5, 4], self.ids("general"))

    def test_reply_count_updates(self):
        self.cache.set_page("general", 1, 1, [summary(3)], False, TODAY)
        self.cache.set_page("general", 1, 1, [summary(3, replies=2)], False, TODAY)
        self.assertEqual(2, self.cache.board_list("general")[0]["replies"])

    def test_fresh_message_needs_matching_replies(self):
        self.cache.put_message("general", full(3, replies=1))
        self.assertIsNotNone(self.cache.fresh_message(3, 1))
        self.assertIsNone(self.cache.fresh_message(3, 2))
        self.assertIsNone(self.cache.fresh_message(4, 0))

    def test_deleted_board_dropped(self):
        self.cache.set_page("motd", 1, 1, [summary(3)], False, TODAY)
        self.cache.put_message("motd", full(3))
        self.cache.set_boards(["general"], False, TODAY)
        self.assertEqual([], self.ids("motd"))
        self.assertIsNone(self.cache.message(3))
        self.assertEqual([], self.cache.archived)

    def test_deleted_board_kept(self):
        self.cache.set_page("motd", 1, 1, [summary(3)], False, TODAY)
        self.cache.put_message("motd", full(3))
        self.cache.set_boards(["general"], True, TODAY)
        archive = self.cache.archived[0]
        self.assertEqual(("motd", TODAY, [3]), (archive["name"], archive["deleted"], [m["id"] for m in archive["list"]]))
        self.assertIsNotNone(self.cache.message(3))

    def test_recreated_board_is_not_mixed(self):
        # motd deleted and made again while this client was away: the old post is not on the new board's list
        self.cache.set_page("motd", 1, 1, [summary(3), summary(2)], True, TODAY)
        self.cache.set_page("motd", 1, 1, [summary(10)], True, TODAY)
        self.assertEqual([10], self.ids("motd"))
        self.assertEqual([3, 2], [message["id"] for message in self.cache.archived[0]["list"]])

    def test_recreated_empty_board(self):
        self.cache.set_page("motd", 1, 1, [summary(3)], False, TODAY)
        self.cache.set_page("motd", 1, 1, [], False, TODAY)
        self.assertEqual([], self.ids("motd"))

    def test_older_page_does_not_retire(self):
        self.cache.set_page("general", 1, 3, [summary(30), summary(29)], False, TODAY)
        self.cache.set_page("general", 3, 3, [summary(2), summary(1)], False, TODAY)
        self.assertEqual([30, 29, 2, 1], self.ids("general"))

    def test_remove_archived(self):
        self.cache.set_page("old", 1, 1, [summary(7)], True, TODAY)
        self.cache.put_message("old", full(7))
        self.cache.set_boards([], True, TODAY)
        self.cache.remove_archived(0)
        self.assertEqual([], self.cache.archived)
        self.assertIsNone(self.cache.message(7))

    def test_usage(self):
        self.assertEqual("No offline copies on this computer.", cache.describe_usage(self.directory))
        self.cache.save("now")
        cache.ServerCache("cd" * 16, self.directory).save("now")
        size, count = cache.usage(self.directory)
        self.assertEqual(2, count)
        self.assertGreater(size, 0)
        self.assertEqual(f"Offline copies use {size} bytes for 2 BBSes.", cache.describe_usage(self.directory))

    def test_delete_all(self):
        self.cache.save("now")
        cache.delete_all(self.directory)
        self.assertFalse(cache.has_any(self.directory))


if __name__ == "__main__":
    unittest.main()
