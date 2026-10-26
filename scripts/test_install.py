import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('installer', Path(__file__).with_name('install_runtime.py'))
i = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i)


class InstallTests(unittest.TestCase):
    def fixture(self, root):
        home = root / 'home'
        target = home / 'Applications/DJOneHub.app'
        data = home / 'Library/Application Support/DJOneHubNetworkMenu'
        source = root / 'source.app'
        for app in (source, target):
            (app / 'Contents/Resources').mkdir(parents=True)
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': i.LABEL}))
        (source / 'Contents/Resources/new').write_text('new app')
        (target / 'Contents/Resources/old').write_text('old app')
        data.mkdir(parents=True)
        (data / 'quota.json').write_text('{"private":"preserve"}')
        upstream = home / 'Library/Application Support/DJOneHub'
        upstream.mkdir(parents=True)
        (upstream / 'usb-profile-intent.json').write_text('keep module profile')
        agents = home / 'Library/LaunchAgents'
        agents.mkdir(parents=True)
        old = plistlib.dumps({'Label': i.BACKEND_LABEL, 'ProgramArguments': ['/old/backend']})
        (agents / (i.BACKEND_LABEL + '.plist')).write_bytes(old)
        return home, target, data, source, old

    def test_upgrade_preserves_private_data_and_backs_up_old_app(self):
        with tempfile.TemporaryDirectory() as d:
            home, target, data, source, old = self.fixture(Path(d))
            with patch.multiple(i, USER_HOME=home, TARGET=target, DATA=data, SOURCE_APP=source), \
                 patch.object(i.os, 'geteuid', return_value=501), patch.object(i, 'backend_ready', return_value=True), \
                 patch.object(i, 'command', side_effect=lambda args, check=True: __import__('types').SimpleNamespace(returncode=1 if 'print' in args else 0, stdout='', stderr='')):
                i.install()
            self.assertTrue((target / 'Contents/Resources/new').exists())
            self.assertEqual((data / 'quota.json').read_text(), '{"private":"preserve"}')
            self.assertEqual((home / 'Library/Application Support/DJOneHub/usb-profile-intent.json').read_text(), 'keep module profile')
            backups = list((data / 'backups').glob('unified-*'))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / 'DJOneHub.app/Contents/Resources/old').exists())
            backend = plistlib.loads((home / 'Library/LaunchAgents' / (i.BACKEND_LABEL + '.plist')).read_bytes())
            self.assertIn(str(target), backend['ProgramArguments'][0])
            native = plistlib.loads((home / 'Library/LaunchAgents' / (i.LABEL + '.plist')).read_bytes())
            self.assertEqual(native['ProgramArguments'][:2], ['/usr/bin/open', '-g'])
            self.assertEqual(native['ProgramArguments'][2], str(target))

    def test_failed_backend_start_restores_old_app_and_agent(self):
        with tempfile.TemporaryDirectory() as d:
            home, target, data, source, old = self.fixture(Path(d))
            failed = []
            def command(args, check=True):
                if 'bootstrap' in args and not failed:
                    failed.append(True)
                    raise RuntimeError('simulated startup failure')
            with patch.multiple(i, USER_HOME=home, TARGET=target, DATA=data, SOURCE_APP=source), \
                 patch.object(i.os, 'geteuid', return_value=501), patch.object(i, 'command', side_effect=command):
                with self.assertRaisesRegex(RuntimeError, 'simulated'):
                    i.install()
            self.assertTrue((target / 'Contents/Resources/old').exists())
            self.assertEqual((home / 'Library/LaunchAgents' / (i.BACKEND_LABEL + '.plist')).read_bytes(), old)
            self.assertEqual((data / 'quota.json').read_text(), '{"private":"preserve"}')

    def test_unknown_target_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);target = root / 'other.app';target.mkdir()
            with patch.object(i, 'TARGET', target), patch.object(i.os, 'geteuid', return_value=501), patch.object(i, 'command') as run:
                with self.assertRaisesRegex(RuntimeError, '不属于'):
                    i.install()
                run.assert_not_called()


    def test_only_exact_owned_frontend_paths_are_stopped(self):
        import signal
        from types import SimpleNamespace
        target = Path('/test/Applications/DJOneHub.app')
        listing = '111 ' + str(target / 'Contents/MacOS/DJOneHub') + '\n222 /Applications/Unrelated.app/Contents/MacOS/Unrelated\n'
        def kill(pid, action):
            if action == 0: raise ProcessLookupError()
        with patch.object(i, 'TARGET', target), patch.object(i, 'USER_HOME', Path('/test')),              patch.object(i, 'command', return_value=SimpleNamespace(stdout=listing)) as listing_command,              patch.object(i.os, 'getpid', return_value=999), patch.object(i.os, 'getppid', return_value=998),              patch.object(i.os, 'kill', side_effect=kill) as terminate:
            i.stop_old_frontends()
        self.assertEqual(listing_command.call_args.args[0], ['/bin/ps', '-U', str(i.os.getuid()), '-o', 'pid=,comm='])
        self.assertEqual(terminate.call_args_list[0].args, (111, signal.SIGTERM))
        self.assertFalse(any(call.args[0] == 222 for call in terminate.call_args_list))


    def test_already_loaded_service_must_match_intended_executable(self):
        from types import SimpleNamespace
        failed = SimpleNamespace(returncode=5, stderr='already loaded')
        for program, expected in [('/right/backend', True), ('/wrong/backend', False)]:
            current = SimpleNamespace(returncode=0, stdout='\tprogram = ' + program + '\n')
            with patch.object(i, 'command', side_effect=[failed, current]):
                if expected: i.bootstrap_service('test.label', Path('/test.plist'), '/right/backend')
                else:
                    with self.assertRaises(RuntimeError):
                        i.bootstrap_service('test.label', Path('/test.plist'), '/right/backend')


if __name__ == '__main__': unittest.main()
