#!/usr/bin/python3
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import time
import datetime
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import urllib.parse

# Isolated bundled Python may import only our adjacent helper module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

VPN_TARGETS = {
    'google': ('Google', 'https://www.google.com/', ()),
    'youtube': ('YouTube', 'https://www.youtube.com/', ()),
    'chatgpt': ('ChatGPT', 'https://chatgpt.com/', ('auth.openai.com',)),
    'claude': ('Claude', 'https://claude.ai/', ()),
    'grok': ('Grok', 'https://grok.com/', ('accounts.x.ai', 'accounts.x.com')),
    'gemini': ('Gemini', 'https://gemini.google.com/', ('accounts.google.com',)),
    'tiktok': ('TikTok', 'https://www.tiktok.com/', ()),
    'x': ('X', 'https://x.com/', ()),
    'instagram': ('Instagram', 'https://www.instagram.com/', ()),
    'facebook': ('Facebook', 'https://www.facebook.com/', ()),
    'wikipedia': ('Wikipedia', 'https://www.wikipedia.org/', ()),
}


def selected_vpn_sites(settings=None):
    settings = read_settings() if settings is None else settings
    chosen = settings.get('vpn_sites', list(VPN_TARGETS))
    if not isinstance(chosen, list):
        chosen = list(VPN_TARGETS)
    return [key for key in VPN_TARGETS if key in chosen]

ROOT = Path.home() / 'Library/Application Support/DJOneHubNetworkMenu'
SETTINGS = ROOT / 'settings.json'
CHECKS = ROOT / 'connectivity.json'
SOCKET = '/var/run/clash-verge-service/users/%d/verge-mihomo.sock' % os.getuid()


def run(args, timeout=12):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or '系统命令失败')
    return p.stdout


def read_settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(data):
    ROOT.mkdir(parents=True, exist_ok=True)
    ROOT.chmod(0o700)
    p = SETTINGS.with_name('settings.%d.tmp' % os.getpid())
    p.write_text(json.dumps(data, ensure_ascii=False))
    p.chmod(0o600)
    p.replace(SETTINGS)


def actual_route(rows):
    try:
        default = run(['/sbin/route', '-n', 'get', 'default'])
    except RuntimeError:
        return 'other', ''
    match = re.search(r'interface:\s*(\S+)', default)
    device = match[1] if match else ''
    current = next((r for r in rows if r.get('device') == device), None)
    mode = '4g' if current and current.get('port') == 'Baiwang' else 'wifi' if current and current.get('port') in ('Wi-Fi', 'AirPort') else 'other'
    return mode, device


def tls_probe(url, proxy_address=None, timeout=10):
    """Like Clash Verge test_delay: verified TLS handshake, no webpage request."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('检测地址必须是 HTTPS')
    host, port = parsed.hostname, parsed.port or 443
    context = ssl.create_default_context()
    if proxy_address:
        connection = http.client.HTTPSConnection(*proxy_address, timeout=timeout, context=context)
        connection.set_tunnel(host, port)
        try:
            connection.connect()
        finally:
            connection.close()
    else:
        with socket.create_connection((host, port), timeout=timeout) as transport:
            with context.wrap_socket(transport, server_hostname=host):
                pass


def check_connectivity():
    mode, device = actual_route(services())
    proxies = urllib.request.getproxies_macosx_sysconf()
    proxy_address = None
    if Path(SOCKET).exists():
        config = proxy_request('GET', '/configs')
        port = config.get('mixed-port')
        if (config.get('tun', {}).get('enable') or proxies.get('https') or proxies.get('http')) and isinstance(port, int) and 1 <= port <= 65535:
            proxy_address = ('127.0.0.1', port)
    targets = {'internet': ('普通联网', 'https://www.baidu.com/', ()),
               **{key: VPN_TARGETS[key] for key in selected_vpn_sites()}}

    def probe(item):
        name, (label, url, login_hosts) = item
        started = time.monotonic()
        result = dict(ok=False, http_status=None, label=label)
        try:
            if name != 'internet':
                tls_probe(url, proxy_address)
                result.update(ok=True, method='proxy-connect-tls' if proxy_address else 'direct-tls')
                return name, {**result, 'latency_ms': round((time.monotonic() - started) * 1000)}
            opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
            request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15'})
            with opener.open(request, timeout=8) as response:
                response.read(4096)
                expected = urllib.parse.urlparse(url).hostname
                final = urllib.parse.urlparse(response.geturl()).hostname or ''
                domain = expected.removeprefix('www.')
                trusted = final == domain or final.endswith('.' + domain) or final in login_hosts
                result.update(http_status=response.status, ok=200 <= response.status < 300 and trusted)
                if not result['ok']:
                    result['error'] = '跳转异常' if not trusted else '访问受限'
        except urllib.error.HTTPError as error:
            result['http_status'] = error.code
            result['error'] = ('访问受限' if error.code in (401, 403, 429) else '网站响应异常') + ' · HTTP %d' % error.code
        except ssl.SSLCertVerificationError:
            result['error'] = 'TLS 证书验证失败'
        except (TimeoutError, socket.timeout):
            result['error'] = '连接超时'
        except Exception:
            result['error'] = '连接失败或超时'
        result['latency_ms'] = round((time.monotonic() - started) * 1000)
        return name, result

    with ThreadPoolExecutor(max_workers=8) as pool:
        tests = dict(pool.map(probe, targets.items()))
    after = actual_route(services())
    changed = after != (mode, device)
    if changed:
        for result in tests.values():
            result.update(ok=False, error='检测期间网络改变，请重试')
    data = dict(mode=mode, device=device, network_changed=changed, tests=tests, probe_version=2,
                checked_at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'))
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = CHECKS.with_name('connectivity.%d.tmp' % os.getpid())
    temporary.write_text(json.dumps(data, ensure_ascii=False))
    temporary.chmod(0o600)
    temporary.replace(CHECKS)
    return data


def services():
    rows = []
    for line in run(['/usr/sbin/networksetup', '-listnetworkserviceorder']).splitlines():
        m = re.match(r'^\(\d+\) (\*?)(.+)$', line)
        if m:
            rows.append(dict(name=m[2], disabled=bool(m[1])))
        m = re.match(r'^\(Hardware Port: (.*), Device: (.*)\)$', line)
        if m and rows:
            rows[-1].update(port=m[1], device=m[2])
    for row in rows:
        link = subprocess.run(['/sbin/ifconfig', row.get('device', '')], capture_output=True, text=True)
        row['connected'] = link.returncode == 0 and bool(re.search(r'status:\s*active\b', link.stdout))
        p = subprocess.run(['/usr/sbin/ipconfig', 'getifaddr', row.get('device', '')], capture_output=True, text=True)
        try:
            address = ipaddress.ip_address(p.stdout.strip())
            row['available'] = row['connected'] and not row['disabled'] and not address.is_link_local and not address.is_unspecified
        except ValueError:
            row['available'] = False
    return rows


def wifi_device(rows):
    return next((r.get('device') for r in rows if r.get('port') in ('Wi-Fi', 'AirPort')), None)


def wifi_power(device):
    return run(['/usr/sbin/networksetup', '-getairportpower', device]).strip().endswith(': On')


def set_wifi_power(device, enabled):
    run(['/usr/sbin/networksetup', '-setairportpower', device, 'on' if enabled else 'off'])


def auto_connect_needed(settings, ready, current_mode='other', wifi_on=False):
    return settings.get('auto_switch', False) and ready and (current_mode != '4g' or wifi_on)


def target(rows, mode):
    return next((r for r in rows if r['available'] and
                 (r.get('port') in ('Wi-Fi', 'AirPort') if mode == 'wifi' else r.get('port') == 'Baiwang')), None)


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(SOCKET)


def proxy_request(method, endpoint, data=None):
    c = UnixHTTP('localhost')
    try:
        body = None if data is None else json.dumps(data)
        c.request(method, endpoint, body, {'Content-Type': 'application/json'})
        r = c.getresponse()
        content = r.read()
        if r.status >= 300:
            raise RuntimeError('Clash 接口返回 HTTP %d' % r.status)
        return json.loads(content) if content else {}
    finally:
        c.close()


def pin_proxy(device, rebuild=False):
    if not Path(SOCKET).exists():
        return False
    config = proxy_request('GET', '/configs')
    previous_interface = config.get('interface-name', '')
    changed = previous_interface != device
    if (changed or rebuild) and config.get('tun', {}).get('enable'):
        groups = proxy_request('GET', '/proxies').get('proxies', {})
        selected = {name: group.get('now') for name, group in groups.items()
                    if group.get('type') == 'Selector'}
        # Rebuild from the core's own current configuration, not a guessed file.
        # PATCH interface-name alone leaves TUN/DNS state on the former uplink.
        proxy_request('PUT', '/configs?force=true', {})
        restore = {key: config[key] for key in ('mode', 'ipv6', 'mixed-port', 'tun') if key in config}
        restore['interface-name'] = device
        proxy_request('PATCH', '/configs', restore)
        for name, choice in selected.items():
            if choice:
                proxy_request('PUT', '/proxies/' + urllib.parse.quote(name, safe=''), {'name': choice})
        # An unchanged TUN configuration is reused by Mihomo even after reload.
        # Recreate it on the new physical uplink to replace its old routes.
        try:
            proxy_request('PATCH', '/configs', {'tun': {'enable': False}})
        finally:
            proxy_request('PATCH', '/configs', {'interface-name': device, 'tun': config['tun']})
        if not proxy_request('GET', '/configs').get('tun', {}).get('enable'):
            raise RuntimeError('代理重建后 TUN 未保持开启，请在 Clash 确认状态')
    else:
        proxy_request('PATCH', '/configs', {'interface-name': device})
    if proxy_request('GET', '/configs').get('interface-name', '') != device:
        raise RuntimeError('Clash 出口接口未更新')
    if changed or rebuild:
        # Old tunnels remain bound to the interface that has just gone offline.
        proxy_request('DELETE', '/connections')
        return True
    # Same-interface refresh only reconnects affected application requests.
    for connection in proxy_request('GET', '/connections').get('connections', []):
        host = connection.get('metadata', {}).get('host', '').lower()
        if any(host == domain or host.endswith('.' + domain)
               for domain in ('youtube.com', 'googlevideo.com', 'ytimg.com', 'youtubei.googleapis.com',
                              'chatgpt.com', 'openai.com', 'oaistatic.com', 'oaiusercontent.com')) or (
                not host and connection.get('metadata', {}).get('process', '').lower().startswith('codex')):
            proxy_request('DELETE', '/connections/' + connection['id'])
    return True


def web_proxy_state(name, secure):
    text = run(['/usr/sbin/networksetup', '-getsecurewebproxy' if secure else '-getwebproxy', name])
    values = dict(line.split(': ', 1) for line in text.splitlines() if ': ' in line)
    if values.get('Authenticated Proxy Enabled') == '1':
        raise RuntimeError('这张网卡已有需要认证的代理，暂不覆盖')
    return dict(enabled=values.get('Enabled') == 'Yes', server=values.get('Server', ''), port=int(values.get('Port') or '0'))


def restore_web_proxy(name, states):
    for secure, old in zip((False, True), states):
        if old['server'] and old['port']:
            run(['/usr/sbin/networksetup', '-setsecurewebproxy' if secure else '-setwebproxy',
                 name, old['server'], str(old['port'])])
        run(['/usr/sbin/networksetup', '-setsecurewebproxystate' if secure else '-setwebproxystate',
             name, 'on' if old['enabled'] else 'off'])


def restore_added_proxies(settings, rows):
    names = {row['name'] for row in rows}
    for name, states in settings.get('web_proxy_backups', {}).items():
        if name in names:
            restore_web_proxy(name, states)


def browser_proxy(name, port, settings):
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise RuntimeError('Clash 代理端口无效')
    previous = [web_proxy_state(name, secure) for secure in (False, True)]
    settings.setdefault('web_proxy_backups', {}).setdefault(name, previous)
    # Save the rollback information before changing any system proxy setting.
    save_settings(settings)
    try:
        for secure in (False, True):
            run(['/usr/sbin/networksetup', '-setsecurewebproxy' if secure else '-setwebproxy',
                 name, '127.0.0.1', str(port)])
            run(['/usr/sbin/networksetup', '-setsecurewebproxystate' if secure else '-setwebproxystate', name, 'on'])
    except Exception:
        restore_web_proxy(name, previous)
        raise


def service_dns(name):
    values = run(['/usr/sbin/networksetup', '-getdnsservers', name]).splitlines()
    return [line.strip() for line in values if valid_address(line.strip())]


def valid_address(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def restore_dns(settings, rows):
    names = {r['name'] for r in rows}
    for name, old in settings.get('dns_backups', {}).items():
        if name in names:
            run(['/usr/sbin/networksetup', '-setdnsservers', name, *(old or ['Empty'])])
    run(['/usr/bin/dscacheutil', '-flushcache'])


def cellular_dns(name, settings):
    deadline = time.monotonic() + 12
    while True:
        try:
            response = run(['/usr/bin/dig', '@127.0.0.1', 'chatgpt.com', 'A', '+short', '+time=2', '+tries=1'])
            if any(valid_address(line.strip()) for line in response.splitlines()):
                break
        except RuntimeError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('Clash 本地 DNS 未响应，已恢复原有网络；请检查代理状态')
        time.sleep(0.5)
    settings.setdefault('dns_backups', {}).setdefault(name, service_dns(name))
    save_settings(settings)
    run(['/usr/sbin/networksetup', '-setdnsservers', name, '127.0.0.1'])
    if service_dns(name) != ['127.0.0.1']:
        raise RuntimeError('4G DNS 未生效')
    run(['/usr/bin/dscacheutil', '-flushcache'])


def modem_info():
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request('http://127.0.0.1:7575/api/at',
                                         data=json.dumps({'command': 'AT+CSQ'}).encode(),
                                         headers={'Content-Type': 'application/json'})
        with op.open(request, timeout=8) as r:
            data = json.load(r)
        match = re.search(r'\+CSQ:\s*(\d+)\s*,', data.get('response', ''))
        strength = int(match[1]) if match else 99
        signal = -113 + 2 * strength if 0 <= strength <= 31 else None
        return dict(signal_dbm=signal, operator='', registration='')
    except Exception:
        return dict(signal_dbm=None, operator='', registration='')


def wake_recover():
    saved = read_settings()
    saved['wake_recovery_until'] = time.time() + 120
    save_settings(saved)
    state = snapshot()
    return dict(ok=True, ready=state['mode'] == '4g' and state['cellular_available'])


def snapshot():
    rows = services()
    modem = target(rows, '4g')
    saved = read_settings()
    connected = any(r.get('port') == 'Baiwang' and r.get('connected') for r in rows)
    error = None
    # Wake may re-enumerate USB or invalidate the existing upstream TCP tunnels.
    if saved.get('wake_recovery_until', 0) > time.time() and modem is not None:
        try:
            switch('4g', rows, remember=False)
            if Path(SOCKET).exists():
                proxy_request('DELETE', '/connections')
            saved = read_settings()
            saved.pop('wake_recovery_until', None)
            save_settings(saved)
            rows = services()
        except Exception as exc:
            error = '唤醒后等待 4G 重连：' + str(exc)
    elif saved.get('wake_recovery_until', 0) <= time.time() and 'wake_recovery_until' in saved:
        saved.pop('wake_recovery_until', None)
        save_settings(saved)
    # Auto mode always uses 4G, independently of the previous manual choice.
    radio = wifi_device(rows)
    current_mode, _ = actual_route(rows)
    if auto_connect_needed(saved, modem is not None, current_mode, wifi_power(radio) if radio else False):
        try:
            switch('4g', rows, remember=False)
        except Exception as exc:
            error = str(exc)
    elif not connected and saved.get('wifi_disabled_by_tool'):
        # Recover the Wi-Fi radio we disabled before hiding the unplugged menu.
        try:
            switch('wifi', rows, remember=False)
        except Exception as exc:
            error = str(exc)
    saved = read_settings()
    saved['cellular_ready'] = modem is not None
    save_settings(saved)
    rows = services()
    modem, wifi = target(rows, '4g'), target(rows, 'wifi')
    mode, interface = actual_route(rows)
    info = modem_info() if modem else dict(signal_dbm=None, operator='', registration='')
    connectivity = None
    try:
        cache = json.loads(CHECKS.read_text())
        if (cache.get('mode') == mode and cache.get('device') == interface and
                cache.get('probe_version') == 2 and
                set(cache.get('tests', {})) == {'internet', *selected_vpn_sites(saved)}):
            connectivity = cache
    except (OSError, ValueError):
        pass
    return dict(mode=mode, device=interface, wifi_available=wifi is not None,
                cellular_available=modem is not None, cellular_connected=connected,
                auto_switch=saved.get('auto_switch', False),
                preferred_mode=saved.get('preferred_mode', saved.get('mode', 'wifi')),
                wifi_power=wifi_power(wifi_device(rows)) if wifi_device(rows) else False,
                automation_error=error, connectivity=connectivity,
                vpn_sites=[dict(id=key, label=value[0], enabled=key in selected_vpn_sites(saved))
                           for key, value in VPN_TARGETS.items()],
                quota=quota_status(connected), **info)


def quota_status(connected):
    from quota_control import snapshot as quota_snapshot
    return quota_snapshot(connected)


def switch(mode, rows=None, remember=True):
    rows = rows or services()
    radio = wifi_device(rows)
    power_before = wifi_power(radio) if radio else False
    if mode == 'wifi' and radio and (not power_before or target(rows, mode) is None):
        if not power_before:
            set_wifi_power(radio, True)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            rows = services()
            if target(rows, mode):
                break
            time.sleep(1)
    selected = target(rows, mode)
    if selected is None:
        raise RuntimeError('Wi-Fi 未取得地址' if mode == 'wifi' else '4G 模块未识别或尚未取得地址')
    names = [r['name'] for r in rows]
    settings = read_settings()
    proxy_before = None
    if Path(SOCKET).exists():
        proxy_before = proxy_request('GET', '/configs').get('interface-name', '')
    settings.setdefault('original_order', names)
    settings.setdefault('original_proxy_interface', proxy_before or '')
    order = [selected['name']] + [name for name in names if name != selected['name']]
    try:
        run(['/usr/sbin/networksetup', '-ordernetworkservices', *order])
        if [r['name'] for r in services()] != order:
            raise RuntimeError('网络服务顺序未生效')
        if mode == 'wifi':
            restore_added_proxies(settings, rows)
            restore_dns(settings, rows)
        if mode == '4g' and radio:
            if power_before:
                settings['wifi_disabled_by_tool'] = True
                save_settings(settings)
            set_wifi_power(radio, False)
            if wifi_power(radio):
                raise RuntimeError('Wi-Fi 未能关闭')
        deadline = time.monotonic() + 10
        while actual_route(rows) != (mode, selected['device']):
            if time.monotonic() >= deadline:
                raise RuntimeError('实际网络出口未切换，请重试')
            time.sleep(0.5)
        # Rebuild only after the physical route and Wi-Fi power have changed.
        proxy = pin_proxy(selected['device'], rebuild=True)
        if mode == '4g' and proxy:
            browser_proxy(selected['name'], proxy_request('GET', '/configs').get('mixed-port'), settings)
            cellular_dns(selected['name'], settings)
    except Exception:
        if radio:
            set_wifi_power(radio, power_before)
        run(['/usr/sbin/networksetup', '-ordernetworkservices', *names])
        if proxy_before is not None:
            proxy_request('PATCH', '/configs', {'interface-name': proxy_before})
        restore_added_proxies(settings, rows)
        restore_dns(settings, rows)
        settings['wifi_disabled_by_tool'] = False
        save_settings(settings)
        raise
    settings.update(mode=mode, device=selected['device'])
    if mode == 'wifi':
        settings['wifi_disabled_by_tool'] = False
    if remember:
        settings['preferred_mode'] = mode
    save_settings(settings)
    return dict(ok=True, mode=mode, device=selected['device'], proxy_updated=proxy)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if action in ('wifi', '4g'):
        if read_settings().get('auto_switch', False):
            raise RuntimeError('请先关闭“自动使用 4G”，再手动选择网络')
        return switch(action)
    if action == 'wake-4g':
        return wake_recover()
    if action == 'test':
        return check_connectivity()
    if action.startswith('vpn-toggle-'):
        key = action.removeprefix('vpn-toggle-')
        if key not in VPN_TARGETS:
            raise RuntimeError('不支持的检测站点')
        saved = read_settings()
        chosen = selected_vpn_sites(saved)
        if key in chosen:
            chosen.remove(key)
        else:
            chosen.append(key)
        saved['vpn_sites'] = chosen
        save_settings(saved)
        CHECKS.unlink(missing_ok=True)
        return dict(ok=True, site=key, enabled=key in chosen)
    if action.startswith('quota-command-'):
        from quota_control import set_command
        return set_command(action.removeprefix('quota-command-'))
    if action.startswith('quota-baseline-'):
        from quota_control import set_manual_baseline
        return set_manual_baseline(action.removeprefix('quota-baseline-'))
    if action == 'quota-sync':
        from quota_control import sync
        return sync()
    if action.startswith('quota-carrier-'):
        from quota_control import set_carrier
        return set_carrier(action.removeprefix('quota-carrier-'))
    if action in ('auto-on', 'auto-off'):
        if action == 'auto-on' and target(services(), '4g') is not None:
            switch('4g')
        saved = read_settings()
        saved['auto_switch'] = action == 'auto-on'
        if saved['auto_switch']:
            saved['preferred_mode'] = '4g'
        save_settings(saved)
        return dict(ok=True, auto_switch=saved['auto_switch'])
    if action == 'automatic':
        saved = read_settings()
        radio = wifi_device(services())
        if radio and saved.get('wifi_disabled_by_tool'):
            set_wifi_power(radio, True)
            saved['wifi_disabled_by_tool'] = False
        restore_added_proxies(saved, services())
        restore_dns(saved, services())
        if Path(SOCKET).exists():
            pin_proxy(saved.get('original_proxy_interface', ''))
        saved['mode'] = 'automatic'
        save_settings(saved)
        return dict(ok=True)
    if action == 'refresh-proxy':
        state = snapshot()
        return dict(ok=True, proxy_updated=pin_proxy(state['device'], rebuild=True) if state['mode'] in ('wifi', '4g') else False)
    return snapshot()


if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(ok=False, error=str(error)), ensure_ascii=False))
        raise SystemExit(1)
