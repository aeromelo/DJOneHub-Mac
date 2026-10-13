import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location('control', Path(__file__).with_name('network_control.py'))
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class Response:
    status = 200

    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, count):
        return b'<html>test only</html>'

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, fail=False, redirect=False):
        self.fail, self.redirect = fail, redirect

    def open(self, url, timeout):
        if isinstance(url, urllib.request.Request):
            url = url.full_url
        if self.fail:
            raise urllib.error.URLError('test only: offline')
        return Response('https://login.invalid/' if self.redirect else url)


class ConnectivityTests(unittest.TestCase):
    def check(self, opener, route_after=('4g', 'en9'), settings=None, tls_fail_sites=()):
        def tls_connect(url, proxy_address=None, timeout=10):
            if opener.fail or any(host in url for host in tls_fail_sites):
                raise OSError('test only: TLS connection failed')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(control, 'ROOT', root), patch.object(control, 'CHECKS', root / 'result.json'), \
                 patch.object(control, 'services', return_value=[]), \
                 patch.object(control, 'read_settings', return_value=settings or {}), \
                 patch.object(control, 'SOCKET', str(root / 'missing.sock')), \
                 patch.object(control, 'tls_probe', side_effect=tls_connect), \
                 patch.object(control, 'actual_route', side_effect=[('4g', 'en9'), route_after]), \
                 patch.object(control.urllib.request, 'getproxies_macosx_sysconf', return_value={}), \
                 patch.object(control.urllib.request, 'build_opener', return_value=opener):
                return control.check_connectivity()

    def test_offline_is_not_reported_as_online(self):
        result = self.check(Opener(fail=True))
        self.assertTrue(all(not probe['ok'] for probe in result['tests'].values()))


    def test_portal_redirect_does_not_prove_internet(self):
        result = self.check(Opener(redirect=True))
        self.assertFalse(result['tests']['internet']['ok'])

    def test_wifi_fallback_cannot_be_mislabeled_as_4g_success(self):
        result = self.check(Opener(), ('wifi', 'en0'))
        self.assertTrue(result['network_changed'])
        self.assertTrue(all(not probe['ok'] for probe in result['tests'].values()))

    def test_website_403_cannot_make_a_tls_connected_site_fail(self):
        class OneRestricted(Opener):
            def open(self, request, timeout):
                url = request.full_url
                if 'claude.ai' in url:
                    raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)
                return Response(url)
        result = self.check(OneRestricted())
        self.assertTrue(result['tests']['claude']['ok'])
        self.assertIsNone(result['tests']['claude']['http_status'])
        self.assertTrue(all(test['ok'] for test in result['tests'].values()))

    def test_single_failed_tls_site_does_not_fail_the_other_sites(self):
        result = self.check(Opener(), tls_fail_sites=('claude.ai',))
        self.assertFalse(result['tests']['claude']['ok'])
        self.assertTrue(all(test['ok'] for key, test in result['tests'].items() if key != 'claude'))

    def test_proxy_probe_performs_verified_tls_without_a_page_request(self):
        with patch.object(control.ssl, 'create_default_context') as context, \
             patch.object(control.http.client, 'HTTPSConnection') as client:
            control.tls_probe('https://chatgpt.com/', ('127.0.0.1', 7897))
            connection = client.return_value
            context.assert_called_once()
            connection.set_tunnel.assert_called_once_with('chatgpt.com', 443)
            connection.connect.assert_called_once()
            connection.request.assert_not_called()
            connection.close.assert_called_once()

    def test_only_selected_vpn_sites_are_requested(self):
        result = self.check(Opener(), settings={'vpn_sites': ['youtube', 'gemini']})
        self.assertEqual(set(result['tests']), {'internet', 'youtube', 'gemini'})

    def test_no_selected_sites_still_checks_ordinary_internet(self):
        result = self.check(Opener(), settings={'vpn_sites': []})
        self.assertEqual(set(result['tests']), {'internet'})


class AutoReconnectTests(unittest.TestCase):
    def test_wake_recovery_rebuilds_tunnels_on_the_current_usb_interface(self):
        import time
        rows = [dict(name='Baiwang', port='Baiwang', device='en10', available=True, connected=True)]
        saved = {'mode': '4g', 'auto_switch': False, 'device': 'en9', 'wake_recovery_until': time.time()+120}
        def save(data):
            saved.clear()
            saved.update(data)
        with tempfile.TemporaryDirectory() as directory:
            socket = Path(directory)/'core.sock'
            socket.touch()
            with patch.object(control, 'SOCKET', str(socket)), \
                 patch.object(control, 'CHECKS', Path(directory)/'checks.json'), \
                 patch.object(control, 'services', return_value=rows), \
                 patch.object(control, 'read_settings', side_effect=lambda: dict(saved)), \
                 patch.object(control, 'save_settings', side_effect=save), \
                 patch.object(control, 'actual_route', return_value=('4g','en10')), \
                 patch.object(control, 'modem_info', return_value={}), \
                 patch.object(control, 'quota_status', return_value=None), \
                 patch.object(control, 'switch') as switch, \
                 patch.object(control, 'proxy_request', return_value={}) as request:
                state=control.snapshot()
                switch.assert_called_once_with('4g', rows, remember=False)
                request.assert_called_once_with('DELETE', '/connections')
                self.assertEqual(state['device'],'en10')
                self.assertFalse(saved['auto_switch'])
                self.assertNotIn('wake_recovery_until', saved)

    def test_auto_off_never_switches_on_insert(self):
        self.assertFalse(control.auto_connect_needed({'auto_switch': False, 'preferred_mode': '4g'}, True))

    def test_auto_on_always_uses_4g_ignoring_old_manual_preference(self):
        saved = {'auto_switch': True, 'preferred_mode': 'wifi', 'cellular_ready': True}
        self.assertTrue(control.auto_connect_needed(saved, True, 'wifi'))
        self.assertFalse(control.auto_connect_needed(saved, False, 'wifi'))
        self.assertFalse(control.auto_connect_needed(saved, True, '4g', False))
        self.assertTrue(control.auto_connect_needed(saved, True, '4g', True))

    def test_manual_switch_is_rejected_when_auto_is_on(self):
        with patch.object(control.sys, 'argv', ['network_control.py', 'wifi']), \
             patch.object(control, 'read_settings', return_value={'auto_switch': True}), \
             patch.object(control, 'switch') as switch:
            with self.assertRaises(RuntimeError):
                control.main()
            switch.assert_not_called()

    def test_closed_wifi_with_stale_ip_is_unavailable(self):
        import subprocess
        output = '(1) Wi-Fi\n(Hardware Port: Wi-Fi, Device: en0)'
        with patch.object(control, 'run', return_value=output), patch.object(control.subprocess, 'run', side_effect=[
            subprocess.CompletedProcess([], 0, 'status: inactive', ''),
            subprocess.CompletedProcess([], 0, '192.168.31.249', '')]):
            self.assertFalse(control.services()[0]['available'])



class ProxyUplinkTests(unittest.TestCase):
    def test_changed_uplink_discards_tunnels_bound_to_the_previous_interface(self):
        def request(method, endpoint, data=None):
            if method == 'GET' and endpoint == '/configs':
                return {'interface-name': 'en0' if not getattr(request, 'updated', False) else 'en9'}
            if method == 'PATCH': request.updated = True
            return {}
        with patch.object(control.Path, 'exists', return_value=True), \
             patch.object(control, 'proxy_request', side_effect=request) as api:
            self.assertTrue(control.pin_proxy('en9'))
        self.assertTrue(any(c.args == ('DELETE', '/connections') for c in api.call_args_list))


class TunnelRebindTests(unittest.TestCase):
    def test_tun_mode_and_manual_selection_survive_uplink_rebuild(self):
        import copy
        current = {'interface-name': 'en0', 'mode': 'rule', 'ipv6': False, 'mixed-port': 7897,
                   'tun': {'enable': True, 'stack': 'system'}}
        restored = {}
        def request(method, endpoint, data=None):
            if method == 'GET' and endpoint == '/configs': return copy.deepcopy(current)
            if method == 'GET' and endpoint == '/proxies':
                return {'proxies': {'AI': {'type': 'Selector', 'now': 'chosen-node'}}}
            if method == 'PUT' and endpoint == '/configs?force=true':
                current.update({'interface-name': '', 'mode': 'direct', 'tun': {'enable': False}})
            if method == 'PATCH': current.update(data)
            if method == 'PUT' and endpoint.startswith('/proxies/'):
                restored[endpoint] = data['name']
            return {}
        with patch.object(control.Path, 'exists', return_value=True), \
             patch.object(control, 'proxy_request', side_effect=request):
            self.assertTrue(control.pin_proxy('en9', rebuild=True))
        self.assertEqual(current['mode'], 'rule')
        self.assertFalse(current['ipv6'])
        self.assertTrue(current['tun']['enable'])
        self.assertEqual(current['interface-name'], 'en9')
        self.assertEqual(restored['/proxies/AI'], 'chosen-node')

class DNSReadinessTests(unittest.TestCase):
    def test_temporary_dns_restart_does_not_abort_network_switch(self):
        with patch.object(control, 'run', side_effect=[RuntimeError('not ready'), '198.18.0.2', '', '']) as command, \
             patch.object(control.time, 'sleep'), patch.object(control, 'save_settings'), \
             patch.object(control, 'service_dns', side_effect=[['223.5.5.5'], ['127.0.0.1']]):
            settings = {}
            control.cellular_dns('USB', settings)
        self.assertEqual(settings['dns_backups']['USB'], ['223.5.5.5'])
        self.assertEqual(sum(c.args[0][0] == '/usr/bin/dig' for c in command.call_args_list), 2)

    def test_persistent_dns_failure_does_not_change_service_dns(self):
        with patch.object(control, 'run', side_effect=RuntimeError('not ready')) as command, \
             patch.object(control.time, 'monotonic', side_effect=[0, 13]), \
             patch.object(control, 'save_settings') as save:
            with self.assertRaisesRegex(RuntimeError, 'DNS'):
                control.cellular_dns('USB', {})
        save.assert_not_called()
        self.assertEqual(command.call_count, 1)

if __name__ == '__main__': unittest.main()
