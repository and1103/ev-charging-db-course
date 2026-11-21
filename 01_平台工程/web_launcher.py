"""Double-click launcher for the local Windows web project.

The batch entry uses the project's Python directly, so .ps1 file associations and
PowerShell script execution policy do not determine whether the application starts.
No credentials, cookies or database connection strings are printed or logged.
"""
import argparse
from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser
from project_paths import PROCESS_ROOT, INSTANCE_ID

ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:5000'
ADDRESS = BASE + '/ui/'
LOGS = PROCESS_ROOT / '本次整合' / '运行日志'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class LaunchError(RuntimeError):
    """A controlled, credential-free error suitable for the user's terminal."""


def health():
    try:
        with build_opener(ProxyHandler({})).open(BASE + '/health', timeout=2) as response:
            result = json.load(response)
        return result if isinstance(result, dict) else None
    except Exception:
        return None


def correct_service(value):
    return bool(value and value.get('status') == 'ok' and value.get('service') == 'charging-backend'
                and value.get('frontend') is True and value.get('instance_id') == INSTANCE_ID)


def port_in_use():
    try:
        with socket.create_connection(('127.0.0.1', 5000), timeout=1):
            return True
    except OSError:
        return False


def preflight():
    required = ['app.py', 'web_ui.py', 'local_runtime.py', 'templates/login.html',
                'templates/workspace.html', '.local/runtime.dpapi']
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        raise LaunchError('工程文件不完整：' + '、'.join(missing) + '。请从完整的Web版文件夹启动。')
    for module in ('flask', 'sqlalchemy', 'pymysql', 'cryptography'):
        try:
            importlib.import_module(module)
        except ImportError:
            raise LaunchError('缺少Python运行依赖，请在第二版根目录双击“安装环境.cmd”。') from None
    from local_runtime import load_runtime
    try:
        load_runtime()
    except Exception:
        raise LaunchError('无法读取本机运行配置。请使用原Windows账号，或重新配置本机数据库连接。') from None
    from sqlalchemy import create_engine, text
    engine = None
    try:
        engine = create_engine(os.environ['CHARGE_DATABASE_URL'])
        with engine.connect() as db:
            schema, port = db.execute(text('SELECT DATABASE(),@@port')).one()
        if schema != 'charge_course_20261114' or port != 3307:
            raise LaunchError('运行配置未连接预期的课设库，请检查本机配置。')
    except LaunchError:
        raise
    except Exception:
        raise LaunchError('数据库连接失败。请确认MySQL服务已启动、3307端口可用，且课设数据库仍然存在。') from None
    finally:
        if engine is not None:
            engine.dispose()


def listener_pid():
    # Read-only process lookup. This executes a command, not a .ps1 script, and
    # does not change PowerShell policy or any Windows security setting.
    command = "Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 5000 -State Listen -ErrorAction Stop | Select-Object -First 1 -ExpandProperty OwningProcess"
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, creationflags=NO_WINDOW)
        value = result.stdout.strip()
        return int(value) if result.returncode == 0 and value.isdecimal() else None
    except Exception:
        return None


def start_service():
    current = health()
    if correct_service(current):
        return False
    if current is not None or port_in_use():
        raise LaunchError('5000端口已被其他程序或旧后端占用。请先关闭原服务，再重新双击启动。')
    python = ROOT / '.venv' / 'Scripts' / 'python.exe'
    if not python.is_file():
        raise LaunchError('本工程虚拟环境不存在，请先运行第二版根目录的“安装环境.cmd”。')
    LOGS.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYTHONIOENCODING='utf-8')
    try:
        with (LOGS / 'server.stdout.log').open('ab') as stdout, (LOGS / 'server.stderr.log').open('ab') as stderr:
            process = subprocess.Popen([str(python), '-X', 'utf8', str(ROOT / 'local_runtime.py'), 'run', 'app.py'],
                                       cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, creationflags=NO_WINDOW)
    except OSError:
        raise LaunchError('无法启动本工程的Python服务，请检查工程目录和虚拟环境。') from None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = health()
        if correct_service(value):
            worker_pid = listener_pid()
            if worker_pid:
                record = {'pid': worker_pid, 'launcher_pid': process.pid, 'project': str(ROOT),
                          'started_at': datetime.now().isoformat(timespec='seconds')}
                (ROOT / '.local' / 'webserver.json').write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8-sig')
            else:
                print('提示：服务已启动，但未取得进程记录；停止时请按5000端口核对本工程服务。')
            return True
        if process.poll() is not None:
            break
        time.sleep(0.3)
    raise LaunchError('网页服务未成功就绪。请查看“过程文件/本次整合/运行日志/server.stderr.log”。')


def owned_process_pattern():
    """Match the exact script invocation, never a PID or Python name alone."""
    executable = r'(?:"[^"]*\\pythonw?\.exe"|[^\s"]*\\pythonw?\.exe)'
    runtime = re.escape(str(ROOT / 'local_runtime.py'))
    return rf'^{executable}\s+(?:-X\s+utf8\s+)?(?:"{runtime}"|{runtime})\s+run\s+(?:"app\.py"|app\.py)\s*$'


def stop_service():
    # Match each current process twice, including creation time, before stopping.
    # The old PID file is deliberately not treated as authority to kill a PID.
    command = r'''
$ErrorActionPreference = 'Stop'
$webPattern = $env:CHARGE_WEB_STOP_PATTERN
function Test-WebOwned($webItem) {
    return ($null -ne $webItem -and $webItem.Name -in @('python.exe','pythonw.exe') -and
        $webItem.CommandLine -and $webItem.CommandLine -match $webPattern)
}
$webItems = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object { Test-WebOwned $_ })
$webStopped = @()
# The redirected worker runs from base Python; stop it before its venv launcher.
$webItems = @($webItems | Sort-Object { if ($_.ExecutablePath -like '*\.venv\Scripts\python.exe') { 1 } else { 0 } })
foreach ($webItem in $webItems) {
    $webCurrent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$webItem.ProcessId)
    if ((Test-WebOwned $webCurrent) -and $webCurrent.CreationDate -eq $webItem.CreationDate) {
        Stop-Process -Id ([int]$webCurrent.ProcessId) -ErrorAction Stop
        $webStopped += [int]$webCurrent.ProcessId
    }
}
Start-Sleep -Milliseconds 250
$webRemaining = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object { Test-WebOwned $_ })
@{ matched=$webItems.Count; stopped=$webStopped.Count; remaining=$webRemaining.Count } | ConvertTo-Json -Compress
'''
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                env=dict(os.environ, CHARGE_WEB_STOP_PATTERN=owned_process_pattern()),
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=25, creationflags=NO_WINDOW)
    except Exception:
        raise LaunchError('无法检查本工程的后台进程，请保留本窗口的提示。') from None
    if result.returncode != 0:
        raise LaunchError('关闭后台进程失败，可能存在进程权限限制；没有按旧PID盲目结束程序。')
    try:
        counts = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise LaunchError('未能读取停止结果，请保留本窗口的提示。') from None
    if counts.get('remaining', 0):
        raise LaunchError('仍有本工程服务进程未退出，请保留本窗口的提示。')
    deadline = time.monotonic() + 4
    while port_in_use() and time.monotonic() < deadline:
        time.sleep(0.2)
    if port_in_use():
        raise LaunchError('5000端口仍被程序使用，但无法确认它属于本工程；未关闭其他程序。')
    (ROOT / '.local' / 'webserver.json').unlink(missing_ok=True)
    return counts.get('stopped', 0) > 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='本机充电平台网页启动器')
    parser.add_argument('--no-browser', action='store_true', help='只启动或检查服务，不打开浏览器')
    parser.add_argument('--check', action='store_true', help='只检查配置、依赖、数据库及当前服务')
    parser.add_argument('--stop', action='store_true', help='关闭本工程后台服务，无需数据库连接')
    args = parser.parse_args(argv)
    try:
        if args.stop:
            stopped = stop_service()
            print('已关闭本工程网页后台服务，5000端口已释放。' if stopped else '本工程后台服务已处于关闭状态，5000端口没有监听。')
            return 0
        print('正在检查本机环境与课设数据库…', flush=True)
        preflight()
        if args.check:
            print('环境与数据库检查通过。')
            print('网页服务：' + ('已运行' if correct_service(health()) else '尚未启动'))
            return 0
        started = start_service()
        print('网页服务已启动。' if started else '网页服务已在运行。')
        print('访问地址：' + ADDRESS)
        if not args.no_browser:
            try:
                if not webbrowser.open(ADDRESS, new=2):
                    print('请手动把上面的地址复制到电脑浏览器。')
            except Exception:
                print('无法自动打开浏览器，请手动访问上面的地址。')
        return 0
    except LaunchError as error:
        print(('停止失败：' if args.stop else '启动失败：') + str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print('启动检查遇到异常（' + type(error).__name__ + '）。请保留本窗口的提示。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
