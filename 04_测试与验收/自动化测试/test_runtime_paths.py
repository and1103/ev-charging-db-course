"""Runtime containment and non-overwriting configuration checks; no DB writes."""
from contextlib import redirect_stderr
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT = next(p for p in Path(__file__).resolve().parents if (p/'01_平台工程/project_paths.py').is_file())
sys.path.insert(0, str(PROJECT/'01_平台工程'))
import local_runtime


class RuntimePaths(unittest.TestCase):
    def test_external_test_folder_is_still_inside_the_project(self):
        target = '04_测试与验收/自动化测试/test_backend_api.py'
        with patch.object(sys, 'argv', ['local_runtime.py','run',target]), patch.object(local_runtime,'load_runtime'), patch.object(local_runtime.runpy,'run_path') as run:
            local_runtime.main()
        run.assert_called_once_with(str(PROJECT/target), run_name='__main__')

    def test_run_refuses_files_outside_project(self):
        target = str(PROJECT.parent/'foreign_project_script.py')
        with patch.object(sys,'argv',['local_runtime.py','run',target]), patch.object(local_runtime,'load_runtime'), patch.object(local_runtime.runpy,'run_path') as run, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                local_runtime.main()
        run.assert_not_called()

    def test_existing_configuration_is_never_replaced(self):
        private = MagicMock()
        private.exists.return_value = True
        with patch.object(local_runtime,'PRIVATE',private), patch('getpass.getpass') as password:
            with self.assertRaises(RuntimeError):
                local_runtime.configure_existing()
        password.assert_not_called()
        private.open.assert_not_called()

    def test_invalid_pii_key_stops_before_database_access(self):
        private = MagicMock()
        private.exists.return_value = False
        with patch.object(local_runtime,'PRIVATE',private), patch('builtins.input',side_effect=['127.0.0.1','test_app_user']), patch('getpass.getpass',side_effect=['synthetic-db-password','invalid-key','synthetic-demo-password']), patch('sqlalchemy.create_engine') as engine:
            with self.assertRaises(RuntimeError):
                local_runtime.configure_existing()
        engine.assert_not_called()
        private.open.assert_not_called()

    def test_plate_cipher_is_checked_when_no_phone_cipher_exists(self):
        from cryptography.fernet import Fernet
        private=MagicMock()
        private.exists.return_value=False
        offered_key=Fernet.generate_key().decode()
        other_cipher=Fernet(Fernet.generate_key()).encrypt(b'synthetic-plate')
        db=MagicMock()
        db.execute.side_effect=[MagicMock(scalar_one_or_none=lambda:'synthetic-hash'),
                                MagicMock(scalar=lambda:None),MagicMock(scalar=lambda:other_cipher)]
        engine=MagicMock()
        engine.connect.return_value.__enter__.return_value=db
        with patch.object(local_runtime,'PRIVATE',private), patch('builtins.input',side_effect=['127.0.0.1','test_app']), patch('getpass.getpass',side_effect=['synthetic-db',offered_key,'synthetic-demo-password']), patch('sqlalchemy.create_engine',return_value=engine), patch('auth.verify',return_value=True):
            with self.assertRaises(RuntimeError):
                local_runtime.configure_existing()
        self.assertEqual(db.execute.call_count,3)
        private.open.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
