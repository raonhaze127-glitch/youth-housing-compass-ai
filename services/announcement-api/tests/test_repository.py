import tempfile
import unittest
from pathlib import Path

from app.repository import UserRepository


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

if __name__ == "__main__":
    unittest.main()
