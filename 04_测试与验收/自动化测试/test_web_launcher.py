"""Launcher behavior checks; browser opening and process creation are mocked."""

# Resolve the integrated project by its marker, not by a fragile parent count.
from pathlib import Path as _BootstrapPath
import sys as _bootstrap_sys
for _base in _BootstrapPath(__file__).resolve().parents:
    _app_candidate = _base / '01_平台工程'
    if (_app_candidate / 'project_paths.py').is_file():
        _bootstrap_sys.path.insert(0, str(_app_candidate))
        _bootstrap_sys.path.insert(0, str(_base / '04_测试与验收'))
        break
else:
    raise RuntimeError('Cannot locate the integrated project root')
from project_paths import APP_ROOT, PROJECT_ROOT, SQL_ROOT, TEST_ROOT, DESIGN_ROOT, BACKUP_ROOT, PROCESS_ROOT, CURRENT_RECORDS, BUSINESS_SQL_DIRS, business_sql_path

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

import web_launcher as launcher

READY = {'status': 'ok', 'service': 'charging-backend', 'frontend': True, 'instance_id': launcher.INSTANCE_ID}


class LauncherChecks(unittest.TestCase):
    def invoke(self, args, **mocks):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(launcher, 'preflight', **mocks), redirect_stdout(output), redirect_stderr(errors):
            code = launcher.main(args)
        return code, output.getvalue(), errors.getvalue()

    def test_expected_service_requires_frontend(self):
        self.assertTrue(launcher.correct_service(READY))
        self.assertFalse(launcher.correct_service({'status': 'ok', 'service': 'charging-backend', 'frontend': False}))
        self.assertFalse(launcher.correct_service({'status': 'ok', 'service': 'unrelated', 'frontend': True}))

    def test_existing_server_is_reused(self):
        with patch.object(launcher, 'health', return_value=READY), patch.object(launcher.subprocess, 'Popen') as process:
            self.assertFalse(launcher.start_service())
            process.assert_not_called()

    def test_busy_port_does_not_start_another_process(self):
        with patch.object(launcher, 'health', return_value=None), patch.object(launcher, 'port_in_use', return_value=True), patch.object(launcher.subprocess, 'Popen') as process:
            with self.assertRaises(launcher.LaunchError):
                launcher.start_service()
            process.assert_not_called()

    def test_check_does_not_start_server_or_browser(self):
        with patch.object(launcher, 'health', return_value=READY), patch.object(launcher, 'start_service') as start, patch.object(launcher.webbrowser, 'open') as browser:
            code, _, _ = self.invoke(['--check', '--no-browser'], return_value=None)
            self.assertEqual(code, 0)
            start.assert_not_called()
            browser.assert_not_called()

    def test_no_browser_mode_never_opens_browser(self):
        with patch.object(launcher, 'start_service', return_value=True), patch.object(launcher.webbrowser, 'open') as browser:
            code, _, _ = self.invoke(['--no-browser'], return_value=None)
            self.assertEqual(code, 0)
            browser.assert_not_called()

    def test_normal_mode_requests_default_browser_only_after_ready(self):
        with patch.object(launcher, 'start_service', return_value=True), patch.object(launcher.webbrowser, 'open', return_value=True) as browser:
            code, _, _ = self.invoke([], return_value=None)
            self.assertEqual(code, 0)
            browser.assert_called_once_with(launcher.ADDRESS, new=2)

    def test_browser_failure_still_offers_manual_address(self):
        with patch.object(launcher, 'start_service', return_value=False), patch.object(launcher.webbrowser, 'open', side_effect=OSError):
            code, output, _ = self.invoke([], return_value=None)
            self.assertEqual(code, 0)
            self.assertIn(launcher.ADDRESS, output)
            self.assertIn('手动', output)

    def test_unexpected_error_does_not_expose_exception_payload(self):
        code, _, errors = self.invoke(['--no-browser'], side_effect=ValueError('DO_NOT_PERSIST_TEST_PAYLOAD'))
        self.assertEqual(code, 1)
        self.assertIn('ValueError', errors)
        self.assertNotIn('DO_NOT_PERSIST_TEST_PAYLOAD', errors)

    def test_stop_matches_exact_project_invocation(self):
        runtime = str(launcher.ROOT / 'local_runtime.py')
        for executable in [r'D:\python 3.12\python.exe', str(launcher.ROOT / '.venv/Scripts/python.exe')]:
            command = subprocess.list2cmdline([executable, '-X', 'utf8', runtime, 'run', 'app.py'])
            self.assertIsNotNone(re.fullmatch(launcher.owned_process_pattern(), command, flags=re.I))

    def test_stop_rejects_other_projects_and_embedded_text(self):
        runtime = str(launcher.ROOT / 'local_runtime.py')
        foreign = str(launcher.ROOT.parent / 'other-project/local_runtime.py')
        commands = [
            subprocess.list2cmdline([r'D:\python 3.12\python.exe', foreign, 'run', 'app.py']),
            subprocess.list2cmdline([r'D:\python 3.12\python.exe', '-c', runtime + ' run app.py']),
            subprocess.list2cmdline([r'D:\python 3.12\python.exe', runtime, 'run', 'different.py']),
        ]
        for command in commands:
            self.assertIsNone(re.fullmatch(launcher.owned_process_pattern(), command, flags=re.I))

    def test_stop_skips_database_preflight_and_browser(self):
        output = io.StringIO()
        with patch.object(launcher, 'preflight') as preflight, patch.object(launcher, 'stop_service', return_value=True), patch.object(launcher.webbrowser, 'open') as browser, redirect_stdout(output):
            self.assertEqual(launcher.main(['--stop']), 0)
        preflight.assert_not_called()
        browser.assert_not_called()
        self.assertIn('已关闭', output.getvalue())

    def test_stop_is_idempotent_without_pid_record(self):
        response = subprocess.CompletedProcess([], 0, json.dumps({'matched': 0, 'stopped': 0, 'remaining': 0}), '')
        with patch.object(launcher.subprocess, 'run', return_value=response), patch.object(launcher, 'port_in_use', return_value=False), patch.object(Path, 'unlink') as unlink:
            self.assertFalse(launcher.stop_service())
            unlink.assert_called_once_with(missing_ok=True)

    def test_stop_refuses_unattributed_listener(self):
        response = subprocess.CompletedProcess([], 0, json.dumps({'matched': 0, 'stopped': 0, 'remaining': 0}), '')
        with patch.object(launcher.subprocess, 'run', return_value=response), patch.object(launcher, 'port_in_use', return_value=True), patch.object(launcher.time, 'monotonic', side_effect=[0, 5]), patch.object(Path, 'unlink') as unlink:
            with self.assertRaises(launcher.LaunchError):
                launcher.stop_service()
            unlink.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
