import tempfile
import unittest
from pathlib import Path

from app.repository import AnnouncementRepository, UserRepository


class UserRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = UserRepository(
            Path(self.temporary_directory.name) / "test.db"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_profile_lifecycle(self):
        self.assertIsNone(self.repository.get_profile("user-1"))
        saved = self.repository.save_profile("user-1", {"age": 28, "region": "서울"})
        self.assertEqual(saved["profile"]["age"], 28)
        self.assertEqual(self.repository.get_profile("user-1")["profile"]["region"], "서울")
        self.assertTrue(self.repository.delete_profile("user-1"))

    def test_favorite_lifecycle(self):
        self.repository.save_favorite("user-1", "apt-1", {"title": "테스트"})
        favorites = self.repository.list_favorites("user-1")
        self.assertEqual(len(favorites), 1)
        self.assertEqual(favorites[0]["announcement"]["title"], "테스트")
        self.assertTrue(self.repository.delete_favorite("user-1", "apt-1"))


class AnnouncementRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = AnnouncementRepository(
            Path(self.temporary_directory.name) / "announcements.db"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_upsert_accumulates_and_tracks_updates(self):
        first = {
            "id": "direct:lh_1",
            "source_id": "lh_1",
            "organization": "LH",
            "title": "첫 공고",
            "fetched_at": "2026-06-20T00:00:00+00:00",
        }
        created = self.repository.upsert([first], "2026-06-20T00:00:00+00:00")
        self.assertEqual(created, {"created": 1, "updated": 0, "unchanged": 0})

        refreshed = {**first, "fetched_at": "2026-06-21T00:00:00+00:00"}
        unchanged = self.repository.upsert([refreshed], "2026-06-21T00:00:00+00:00")
        self.assertEqual(unchanged["unchanged"], 1)

        changed = {**refreshed, "title": "정정 공고"}
        updated = self.repository.upsert([changed], "2026-06-21T01:00:00+00:00")
        self.assertEqual(updated["updated"], 1)
        self.assertEqual(self.repository.count(), 1)
        self.assertEqual(self.repository.list_payloads()[0]["title"], "정정 공고")
        changes = self.repository.list_changes(change_type="updated")
        self.assertEqual(changes["source"], "direct_sqlite_history")
        self.assertEqual(changes["count"], 1)
        self.assertEqual(changes["changes"][0]["field_changes"]["title"]["after"], "정정 공고")

    def test_sync_state_is_persisted(self):
        self.repository.record_sync(
            "direct", "2026-06-14", "2026-06-21", 12, "2026-06-21T22:00:00+00:00"
        )
        state = self.repository.sync_state("direct")
        self.assertEqual(state["window_start"], "2026-06-14")
        self.assertEqual(state["item_count"], 12)

if __name__ == "__main__":
    unittest.main()
