"""Administrator dispatch safety; all credentials, engines and tasks are mocked."""
from contextlib import redirect_stderr
import importlib.util
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT=next(p for p in Path(__file__).resolve().parents if (p/'01_平台工程/project_paths.py').is_file())
sys.path.insert(0,str(PROJECT/'01_平台工程'))
import local_runtime
spec=importlib.util.spec_from_file_location('v2_admin_run',PROJECT/'02_数据库脚本/部署工具/admin_run.py')
admin=importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


class AdminTasks(unittest.TestCase):
    def run_task(self,args,objects):
        engine=MagicMock()
        db=engine.connect.return_value.__enter__.return_value
        db.execute.return_value.scalar_one.return_value=objects
        calls=[]
        def run(path,run_name):
            calls.append((Path(path).name,list(sys.argv[1:])))
        with patch.object(sys,'argv',['admin_run.py',*args]), patch.object(local_runtime,'load_runtime'), patch.object(admin,'getpass',return_value='synthetic-admin-password'), patch('sqlalchemy.create_engine',return_value=engine), patch.object(admin.runpy,'run_path',side_effect=run), patch.dict(os.environ,{'CHARGE_DEMO_PASSWORD':'synthetic-demo-password','CHARGE_ADMIN_DSN':'previous-test-value'}), redirect_stderr(io.StringIO()):
            result=admin.main()
            self.assertEqual(os.environ['CHARGE_ADMIN_DSN'],'previous-test-value')
        return result,calls,engine

    def test_existing_schema_is_not_initialized(self):
        result,calls,engine=self.run_task(['init'],44)
        self.assertEqual(result,1)
        self.assertEqual(calls,[])
        engine.dispose.assert_called_once()

    def test_empty_schema_runs_complete_initialization_in_order(self):
        result,calls,_=self.run_task(['init'],0)
        self.assertEqual(result,0)
        self.assertEqual(calls,[('deploy_local.py',['--demo']),('seed_extended.py',[]),('seed_fleet.py',[])])

    def test_clean_build_forwards_new_target(self):
        result,calls,_=self.run_task(['clean-build','--target','charge_course_verify_synthetic'],0)
        self.assertEqual(result,0)
        self.assertEqual(calls,[('verify_clean_build.py',['--target','charge_course_verify_synthetic'])])

    def test_help_does_not_request_password(self):
        with patch.object(sys,'argv',['admin_run.py','--help']),patch.object(admin,'getpass') as password,patch('sys.stdout',new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as raised:admin.main()
        self.assertEqual(raised.exception.code,0)
        password.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
