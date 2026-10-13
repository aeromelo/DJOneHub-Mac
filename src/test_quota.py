import unittest
from unittest.mock import patch
import quota_control as q


class QuotaTests(unittest.TestCase):
    def test_three_carrier_reply_styles_and_restricted_data(self):
        for message, expected in [
            ('【中国电信】本月国内通用流量剩余 5.50GB，定向流量剩余30GB', int(5.5 * 1024**3)),
            ('【中国移动】套餐内通用流量已用100MB，剩余流量: 1024MB。', 1024**3),
            ('【中国联通】国内流量剩余2048 MB；闲时流量剩余20GB', 2 * 1024**3),
            ('通用流量包一剩余10GB；通用流量包二剩余20GB', None),
            ('定向流量剩余50GB；话费余额100元', None),
            ('套餐不限量', None)]:
            with self.subTest(message=message):
                self.assertEqual(q.parse_remaining(message), expected)

    def test_telecom_numbered_shared_packages_and_carryover(self):
        message = ('1、国内上网(群组共享)共40960.0MB，已用0.0MB；\n'
                   '2、国内上网(上月结转)共40960.0MB，已用0.0MB；\n'
                   '3、国内上网共160GB，已用10.38GB；\n'
                   '4、国内通话共500分钟，已用4分钟；')
        self.assertEqual(q.parse_remaining(message), round(229.62 * 1024**3))

    def test_counters_persist_reset_and_do_not_count_wifi(self):
        card = {'used_bytes': 0}
        def sample(rx, tx, interface='en9'):
            q.accumulate(card, dict(available=True, interface=interface, rx_bytes=rx, tx_bytes=tx))
        sample(1000, 100)
        sample(1500, 300)
        self.assertEqual(card['used_bytes'], 700)
        sample(100, 50)
        self.assertEqual(card['used_bytes'], 850)
        q.accumulate(card, {'available': False})
        sample(9999, 999)
        self.assertEqual(card['used_bytes'], 850)

    def test_sms_is_not_sent_by_status_polling(self):
        card = {'used_bytes': 100, 'remaining_bytes': 1000, 'baseline_used': 0}
        with patch.object(q, 'load', return_value={'cards': {'test': card}}), \
             patch.object(q, 'identify', return_value=card), patch.object(q, 'save'), \
             patch.object(q, 'api', return_value={'available': False}) as request:
            result = q.snapshot(True)
            self.assertEqual(result['remaining_bytes'], 900)
            self.assertFalse(any(call.args[0] == 'sms/send' for call in request.call_args_list))


    def test_sim_change_cancels_previous_pending_query(self):
        old = {'pending': {'number': '10010'}, 'counter': ['en9', 100, 50]}
        data = {'card': 'previous-card', 'cards': {'previous-card': old}}
        with patch.object(q, 'api', return_value={'iccid': '12345678901234567890', 'imsi': '460011234567890'}):
            card = q.identify(data, force=True)
        self.assertNotIn('pending', old)
        self.assertNotIn('counter', old)
        self.assertEqual(card['detected_carrier'], 'unicom')
        self.assertNotEqual(data['card'], 'previous-card')

    def test_operator_app_link_or_invalid_command_is_not_a_balance(self):
        import datetime, time
        for text, status in [
            ('请点击链接跳转到中国联通APP查询流量使用情况', '短信未返回流量额度'),
            ('很抱歉，未能理解您要办的业务，请输入正确的业务编码', '未被运营商识别')]:
            card = {'pending': {'number': '10010', 'seen': [], 'sent_at': time.time()}}
            message = {'sender': '10010', 'timestamp': datetime.datetime.now().astimezone().isoformat(), 'content': text}
            with patch.object(q, 'api', return_value=[message]): q.receive(card)
            self.assertNotIn('pending', card)
            self.assertNotIn('remaining_bytes', card)
            self.assertIn(status, card['status'])


if __name__ == '__main__':
    unittest.main()
