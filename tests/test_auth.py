import unittest
from unittest.mock import patch

import auth


class AdminTokenTest(unittest.TestCase):
    def test_rejects_when_no_token_configured(self):
        with patch.object(auth, "get_admin_access_token", return_value=None):
            self.assertFalse(auth.is_valid_admin_token("anything"))

    def test_rejects_empty_provided_token(self):
        with patch.object(auth, "get_admin_access_token", return_value="secret123"):
            self.assertFalse(auth.is_valid_admin_token(None))
            self.assertFalse(auth.is_valid_admin_token(""))

    def test_rejects_wrong_token(self):
        with patch.object(auth, "get_admin_access_token", return_value="secret123"):
            self.assertFalse(auth.is_valid_admin_token("wrong-token"))

    def test_accepts_matching_token(self):
        with patch.object(auth, "get_admin_access_token", return_value="secret123"):
            self.assertTrue(auth.is_valid_admin_token("secret123"))


if __name__ == "__main__":
    unittest.main()
