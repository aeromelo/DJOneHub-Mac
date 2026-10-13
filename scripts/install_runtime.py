"""Offline, user-only unified App installer; preserves SIM data and module setup."""
import datetime
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import json

RESOURCES = Path(__file__).resolve().parent
SOURCE_APP = RESOURCES.parent.parent
USER_HOME = Path.home()
TARGET = USER_HOME / 'Applications/DJOneHub.app'
DATA = USER_HOME / 'Library/Application Support/DJOneHubNetworkMenu'
LABEL = 'com.jonyyan.djonehub.networkmenu'
BACKEND_LABEL = 'com.jamie.djonehub'
LEGACY_LABEL = 'com.jamie.djonehub-notifier'


def command(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(' '.join(str(a) for a in args[:3]) + ': ' + result.stderr.strip()[:500])
    return result


def backend_ready():
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open('http://127.0.0.1:7575/api/health', timeout=2) as response:
            return json.load(response).get('ok') is True
    except Exception:
        return False


def owned_app(path):
    if not path.exists():
        return not path.is_symlink()
    try:
        info = plistlib.loads((path / 'Contents/Info.plist').read_bytes())
        return info.get('CFBundleIdentifier') in (LABEL, 'com.jamie.djonehub.notifier', 'io.github.aeromelo.djonehub.mac')
    except Exception:
        return False




def bootstrap_service(label, plist, program):
    result = command(['/bin/launchctl', 'bootstrap', 'gui/%d' % os.getuid(), str(plist)], check=False)
    if getattr(result, 'returncode', 0) == 0: return
    # macOS can already load a newly written LaunchAgent. Accept that only
    # when the active service points to the exact intended executable.
    current = command(['/bin/launchctl', 'print', 'gui/%d/%s' % (os.getuid(), label)], check=False)
    text = getattr(current, 'stdout', '')
    if getattr(current, 'returncode', 1) == 0 and isinstance(text, str):
        if ('program = ' + str(program) + '\n') in text:
            return
    raise RuntimeError('启动 ' + label + ' 失败：' + getattr(result, 'stderr', '')[:500])


def stop_old_frontends():
    # Existing manual native windows also try to bootstrap the backend; stop
    # their exact owned executable paths before replacing its LaunchAgent.
    paths = {
        str(TARGET / 'Contents/MacOS/DJOneHub'),
        str(TARGET.with_name('DJOneHub网络切换.app') / 'Contents/MacOS/NetworkMenu'),
        str(USER_HOME / 'Library/Application Support/DJOneHub/notifier/DJOneHubNotifier.app/Contents/MacOS/DJOneHubNotifier'),
    }
    result = command(['/bin/ps', '-axo', 'pid=,comm='])
    output = getattr(result, 'stdout', '')
    if not isinstance(output, str): return
    for row in output.splitlines():
        fields = row.strip().split(None, 1)
        if len(fields) != 2 or fields[1] not in paths: continue
        pid = int(fields[0])
        if pid in (os.getpid(), os.getppid()): continue
        try: os.kill(pid, signal.SIGTERM)
        except ProcessLookupError: continue
        for _ in range(50):
            try: os.kill(pid, 0)
            except ProcessLookupError: break
            time.sleep(0.1)
        else: raise RuntimeError('旧 DJOneHub 窗口未退出，请关闭后重试')


def install():
    if os.geteuid() == 0:
        raise RuntimeError('请以正常登录用户安装，不要使用 sudo')
    if not owned_app(TARGET):
        raise RuntimeError('同名程序或链接不属于 DJOneHub，未覆盖')
    legacy = TARGET.with_name('DJOneHub网络切换.app')
    if legacy.exists() and not owned_app(legacy):
        raise RuntimeError('旧菜单程序不属于 DJOneHub，未覆盖')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    agents = USER_HOME / 'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)
    logs = USER_HOME / 'Library/Logs/DJOneHub'
    logs.mkdir(parents=True, exist_ok=True)
    backup = DATA / 'backups' / ('unified-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    DATA.chmod(0o700)
    backup.chmod(0o700)
    labels = (LABEL, LEGACY_LABEL, BACKEND_LABEL)
    old_plists = {}
    moved = []
    staging = TARGET.with_name('.DJOneHub-install-%d.app' % os.getpid())
    shutil.copytree(SOURCE_APP, staging, symlinks=True)
    for label in labels:
        path = agents / (label + '.plist')
        if path.exists():
            old_plists[label] = path.read_bytes()
            (backup / (label + '.plist')).write_bytes(old_plists[label])
    try:
        # Remove stale registration files first so old windows/system watchers
        # cannot re-bootstrap their old backend while we migrate it.
        for label in labels:
            (agents / (label + '.plist')).unlink(missing_ok=True)
        for label in (LABEL, LEGACY_LABEL):
            command(['/bin/launchctl', 'bootout', 'gui/%d/%s' % (os.getuid(), label)], check=False)
        stop_old_frontends()
        command(['/bin/launchctl', 'bootout', 'gui/%d/%s' % (os.getuid(), BACKEND_LABEL)], check=False)
        for _ in range(50):
            old = command(['/bin/launchctl', 'print', 'gui/%d/%s' % (os.getuid(), BACKEND_LABEL)], check=False)
            if getattr(old, 'returncode', 1) != 0: break
            time.sleep(0.1)
        for path in (TARGET, legacy):
            if path.exists() or path.is_symlink():
                destination = backup / path.name
                shutil.move(str(path), str(destination))
                moved.append((path, destination))
        staging.rename(TARGET)
        command(['/usr/bin/xattr', '-dr', 'com.apple.quarantine', str(TARGET)], check=False)
        runtime = TARGET / 'Contents/Resources/upstream/djonehub'
        backend = dict(Label=BACKEND_LABEL, ProgramArguments=[str(runtime / 'bin/djonehub-macos'), '-listen', '127.0.0.1:7575'],
                       RunAtLoad=True, KeepAlive=True, ThrottleInterval=5, ProcessType='Background',
                       WorkingDirectory=str(runtime), StandardOutPath=str(logs / 'launchd.log'), StandardErrorPath=str(logs / 'launchd.log'))
        native = dict(Label=LABEL, ProgramArguments=['/usr/bin/open', '-g', str(TARGET), '--args', '--background'],
                      RunAtLoad=True, ProcessType='Interactive', StandardOutPath=str(logs / 'networkmenu.log'), StandardErrorPath=str(logs / 'networkmenu.log'))
        for label, info in ((BACKEND_LABEL, backend), (LABEL, native)):
            (agents / (label + '.plist')).write_bytes(plistlib.dumps(info))
        (agents / (LEGACY_LABEL + '.plist')).unlink(missing_ok=True)
        bootstrap_service(BACKEND_LABEL, agents / (BACKEND_LABEL + '.plist'), runtime / 'bin/djonehub-macos')
        for _ in range(40):
            if backend_ready(): break
            time.sleep(0.25)
        if not backend_ready():
            raise RuntimeError('后台未就绪，正在恢复之前的安装')
        bootstrap_service(LABEL, agents / (LABEL + '.plist'), '/usr/bin/open')
    except Exception:
        for label in labels:
            command(['/bin/launchctl', 'bootout', 'gui/%d/%s' % (os.getuid(), label)], check=False)
        if TARGET.exists() and not TARGET.is_symlink(): shutil.rmtree(TARGET)
        for path, saved in reversed(moved): shutil.move(str(saved), str(path))
        for label in labels:
            path = agents / (label + '.plist')
            if label in old_plists:
                path.write_bytes(old_plists[label])
            else: path.unlink(missing_ok=True)
        for label in (BACKEND_LABEL, LEGACY_LABEL, LABEL):
            if label in old_plists:
                command(['/bin/launchctl', 'bootstrap', 'gui/%d' % os.getuid(), str(agents / (label + '.plist'))], check=False)
        raise
    finally:
        if staging.exists(): shutil.rmtree(staging)
    command(['/usr/bin/open', str(TARGET)], check=False)
    print('安装完成：%s；旧程序和启动配置备份在 %s' % (TARGET, backup))


if __name__ == '__main__':
    try:
        install()
    except Exception as error:
        print('安装失败：%s' % error, file=sys.stderr)
        sys.exit(1)
