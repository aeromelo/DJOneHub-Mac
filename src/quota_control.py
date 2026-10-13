"""Carrier SMS baseline, then local USB RX+TX estimates. Never sends on polling."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata
import urllib.request

ROOT = Path.home() / 'Library/Application Support/DJOneHubNetworkMenu'
FILE = ROOT / 'quota.json'
CARRIERS = {
    'telecom': ('中国电信', '10001', '108'),
    'mobile': ('中国移动', '10086', 'CXLL'),
    'unicom': ('中国联通', '10010', 'CXTCYL'),
}
UNICOM_COMMANDS = ('CXTCYL', '2082', 'CXLL', '1071', 'CXLLJ', 'CXYE', 'CXTC', 'CXTQ')


def api(path, data=None):
    request = urllib.request.Request('http://127.0.0.1:7575/api/' + path,
                                    data=None if data is None else json.dumps(data).encode(),
                                    headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            return json.load(response)
    except Exception:
        raise RuntimeError('模块接口暂时不可用，请确认模块已连接') from None


def load():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {'cards': {}}


def save(data):
    ROOT.mkdir(parents=True, exist_ok=True)
    ROOT.chmod(0o700)
    temporary = FILE.with_name('quota.%d.tmp' % os.getpid())
    temporary.write_text(json.dumps(data, ensure_ascii=False))
    temporary.chmod(0o600)
    temporary.replace(FILE)


def identify(data, force=False):
    if force or not data.get('connected') or time.time() - data.get('identity_checked', 0) > 60:
        status = api('status')
        iccid = status.get('iccid', '').strip()
        if not re.fullmatch(r'\d{15,24}', iccid):
            raise RuntimeError('尚未读到 SIM 卡，无法建立独立的套餐统计')
        new_card = hashlib.sha256(iccid.encode()).hexdigest()
        if data.get('card') != new_card:
            for previous in data.setdefault('cards', {}).values():
                if previous.pop('pending', None):
                    previous['status'] = 'SIM 已变更，请重新短信同步'
                previous.pop('counter', None)
        data['card'] = new_card
        prefix = status.get('imsi', '')[:5]
        carrier = ('telecom' if prefix in ('46003', '46005', '46011') else
                   'unicom' if prefix in ('46001', '46006', '46009') else
                   'mobile' if prefix in ('46000', '46002', '46004', '46007', '46008', '46013') else '')
        card = data.setdefault('cards', {}).setdefault(data['card'], {'used_bytes': 0})
        card['detected_carrier'] = carrier
        data['identity_checked'] = time.time()
    data['connected'] = True
    return data['cards'][data['card']]


def accumulate(card, traffic):
    if not traffic.get('available'):
        card.pop('counter', None)
        return
    counter = [traffic['interface'], int(traffic['rx_bytes']), int(traffic['tx_bytes'])]
    previous = card.get('counter')
    if previous and previous[0] == counter[0]:
        # Reset counters start a new session; never subtract or double-count old bytes.
        delta = sum(current - old if current >= old else current
                    for current, old in zip(counter[1:], previous[1:]))
        card['used_bytes'] = card.get('used_bytes', 0) + delta
    card['counter'] = counter


def parse_remaining(text):
    text = unicodedata.normalize('NFKC', text).replace(',', '')
    pattern = re.compile(r'(?:剩余|剩下|余量|可用)(?:的)?(?:[国内全国通用手机上网总]+)?(?:流量)?\s*[:：为是约]*\s*(\d+(?:\.\d+)?)\s*(GB|MB|KB|G|M|K)(?![A-Za-z])', re.I)
    candidates = []
    for part in re.split(r'[；;。\n]', text):
        for match in pattern.finditer(part):
            prefix = part[:match.start()]
            markers = list(re.finditer(r'通用|国内|全国|定向|专属|闲时|夜间|省内|国际|港澳台|共享', prefix))
            scope = markers[-1].group() if markers else ''
            if scope in ('定向', '专属', '闲时', '夜间', '省内', '国际', '港澳台'):
                continue
            # An overall unrestricted amount takes priority; do not add package totals twice.
            rank = 2 if scope == '通用' else 1 if scope in ('国内', '全国') else 0
            factor = {'G': 1024**3, 'M': 1024**2, 'K': 1024}[match[2].upper()[0]]
            candidates.append((rank, round(float(match[1]) * factor)))
    if not candidates:
        # Telecom replies enumerate independent domestic allowances as total/used,
        # including carry-over. Only sum numbered packages, never summary + detail.
        allowances = []
        numbered = []
        for line in text.splitlines():
            if not re.search(r'国内(?:上网|流量)|全国(?:上网|流量)|通用流量', line) or re.search(r'定向|专属|闲时|夜间|省内|国际|港澳台', line):
                continue
            match = re.search(r'(?:共|总量(?:为)?|总计)\s*(\d+(?:\.\d+)?)\s*(GB|MB|KB|G|M|K).*?(?:已用|已使用)\s*(\d+(?:\.\d+)?)\s*(GB|MB|KB|G|M|K)', line, re.I)
            if match:
                factor = {'G': 1024**3, 'M': 1024**2, 'K': 1024}
                total = float(match[1]) * factor[match[2].upper()[0]]
                used = float(match[3]) * factor[match[4].upper()[0]]
                if used > total:
                    return None
                allowances.append(round(total - used))
                numbered.append(bool(re.match(r'\s*\d+[、.．)]', line)))
        return sum(allowances) if allowances and (len(allowances) == 1 or all(numbered)) else None
    best = max(rank for rank, _ in candidates)
    values = {value for rank, value in candidates if rank == best}
    # Ambiguous multiple packages need a carrier summary, not an invented aggregate.
    return values.pop() if len(values) == 1 else None


def carrier_for(card):
    return card.get('carrier_override') or card.get('detected_carrier', '')


def sms_key(message):
    return hashlib.sha256((message.get('sender', '') + message.get('timestamp', '') + message.get('content', '')).encode()).hexdigest()


def receive(card):
    pending = card.get('pending')
    if not pending:
        return
    replies = [m for m in api('sms') if m.get('sender', '').lstrip('+') == pending['number'] and
               sms_key(m) not in pending['seen']]
    replies.sort(key=lambda m: m.get('timestamp', ''), reverse=True)
    for message in replies:
        try:
            stamp = datetime.datetime.fromisoformat(message['timestamp'].replace('Z', '+00:00')).timestamp()
        except (ValueError, KeyError):
            continue
        if stamp < pending['sent_at'] - 5:
            continue
        remaining = parse_remaining(message.get('content', ''))
        if remaining is not None:
            card.update(remaining_bytes=remaining, baseline_used=card.get('used_bytes', 0),
                        synced_at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                        status='已同步', sync_month=datetime.datetime.now().strftime('%Y-%m'),
                        shared='共享' in message.get('content', ''))
            card.pop('pending', None)
            return
        if re.search(r'未能理解|无效指令|正确的业务编码|指令.{0,8}(?:错误|不正确)', message.get('content', '')):
            card.pop('pending', None)
            card['status'] = '该查询指令未被运营商识别，请更换指令后同步'
            return
        if re.search(r'(?:跳转到|前往|请.{0,6}点击).{0,100}(?:APP|App|app)|中国联通APP', message.get('content', '')):
            card.pop('pending', None)
            card['status'] = '运营商要求在官方 App 查询，短信未返回流量额度'
            return
        card['status'] = '已收到回复，未识别通用流量；请在 DJOneHub 查看'
    if time.time() - pending['sent_at'] > 180:
        card.pop('pending', None)
        if not replies:
            card['status'] = '未收到查询回复，可点击短信同步重试'


def view(card):
    used = max(0, card.get('used_bytes', 0) - card.get('baseline_used', 0))
    remaining = card.get('remaining_bytes')
    stale = card.get('sync_month') not in (None, datetime.datetime.now().strftime('%Y-%m'))
    return dict(carrier=carrier_for(card), carrier_name=CARRIERS.get(carrier_for(card), ('未识别运营商',))[0],
                remaining_bytes=None if remaining is None or stale else max(0, remaining - used),
                used_bytes=used, synced_at=card.get('synced_at'),
                pending=bool(card.get('pending')), status='已跨月，请短信同步' if stale else card.get('status', '首次使用，请短信同步'),
                estimated=True, shared=card.get('shared', False),
                query_command=card.get('query_command') or CARRIERS.get(carrier_for(card), ('', '', ''))[2])


def snapshot(connected):
    data = load()
    if not connected:
        data['connected'] = False
        for card in data.get('cards', {}).values():
            card.pop('counter', None)
        save(data)
        return None
    try:
        card = identify(data)
        accumulate(card, api('network/traffic'))
        receive(card)
        save(data)
        return view(card)
    except RuntimeError as exc:
        return dict(carrier='', carrier_name='', remaining_bytes=None, used_bytes=0,
                    synced_at=None, pending=False, status=str(exc), estimated=True)


def sync():
    data = load()
    card = identify(data, force=True)
    accumulate(card, api('network/traffic'))
    carrier = carrier_for(card)
    if carrier not in CARRIERS:
        raise RuntimeError('请选择电信、联通或移动后再同步')
    if card.get('pending') and time.time() - card['pending']['sent_at'] < 180:
        return dict(ok=True, message='查询已发送，正在等待运营商回复')
    if time.time() - card.get('last_sent', 0) < 60:
        raise RuntimeError('请间隔至少一分钟再发送查询短信')
    name, number, command = CARRIERS[carrier]
    if carrier == 'unicom':
        command = card.get('query_command', 'CXTCYL')
        if command not in UNICOM_COMMANDS:
            raise RuntimeError('不支持的联通查询指令')
    seen = [sms_key(m) for m in api('sms') if m.get('sender', '').lstrip('+') == number]
    sent_at = time.time()
    result = api('sms/send', {'phone': number, 'message': command})
    if not result.get('sent'):
        raise RuntimeError('短信发送未成功，请稍后重试')
    card.update(pending={'number': number, 'sent_at': sent_at, 'seen': seen},
                last_sent=sent_at, status='已向%s发送查询，等待回复' % name)
    save(data)
    return dict(ok=True, carrier=name, number=number, command=command, sent=True)


def set_carrier(carrier):
    if carrier not in (*CARRIERS, 'auto'):
        raise RuntimeError('不支持的运营商')
    data = load()
    card = identify(data, force=True)
    if carrier == 'auto':
        card.pop('carrier_override', None)
    else:
        card['carrier_override'] = carrier
    save(data)
    return dict(ok=True)


def set_command(command):
    if command not in UNICOM_COMMANDS:
        raise RuntimeError('不支持的联通查询指令')
    data = load()
    card = identify(data, force=True)
    if carrier_for(card) != 'unicom':
        raise RuntimeError('请先连接联通 SIM 卡并选择联通')
    card['query_command'] = command
    card.pop('pending', None)
    save(data)
    return dict(ok=True, command=command)
