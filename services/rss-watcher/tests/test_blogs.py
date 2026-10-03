import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault("BRIEFING_RECIPIENT", "+10000000000")
from rss_watcher.blog_fetch import fetch, fetch_source, html_entries, intent_entries, plain_text, safe_url
from rss_watcher.blogs import build_brief

NOW = datetime(2026, 9, 29, 17, tzinfo=timezone.utc)
TZ = ZoneInfo("America/Phoenix")
SOURCE = {"name": "Example", "url": "https://example.com/blog", "hosts": ["example.com"], "cards": "article", "date": "time"}


class BlogTests(unittest.TestCase):
    def test_blog_delivery_uses_personal_recipient_not_rss_group(self):
        from rss_watcher.blogs import run_blog_brief
        with patch.dict(os.environ, {'BLOG_RECIPIENT': '', 'BRIEFING_RECIPIENT': '+10000000000',
                                     'RSS_RECIPIENT': 'group.do-not-send'}), patch(
                'rss_watcher.blogs.collect', return_value=[]), patch(
                'rss_watcher.blogs.send_brief') as send:
            run_blog_brief()
        self.assertEqual(send.call_args.args[1], '+10000000000')
        self.assertFalse(send.call_args.kwargs['allow_voice'])

    def test_blog_group_recipient_rejected_before_work_or_send(self):
        from rss_watcher.blogs import run_blog_brief
        with patch.dict(os.environ, {'BLOG_RECIPIENT': 'group.do-not-send'}), patch(
                'rss_watcher.blogs.collect') as collect, patch('rss_watcher.blogs.send_brief') as send:
            with self.assertRaisesRegex(ValueError, 'personal'):
                run_blog_brief()
        collect.assert_not_called()
        send.assert_not_called()

    def test_dates_dedup_and_unsafe_links(self):
        def card(date, link="/post", title="Post"):
            return f'<article><h2>{title}</h2><time datetime="{date}"></time><a href="{link}">Read</a></article>'
        html = (card("2026-09-23") * 2 + card("2026-09-21") + card("2026-09-30")
                + card("2026-09-24", "https://evil.example/") + card("not a date"))
        items = fetch_source(SOURCE, now=NOW, tz=TZ, getter=lambda *_: html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["link"], "https://example.com/post")

    def test_feed_boundaries_and_missing_dates(self):
        dates = ["Tue, 22 Sep 2026 17:00:00 GMT", "Tue, 22 Sep 2026 16:59:59 GMT", "Tue, 29 Sep 2026 17:00:01 GMT", None]
        xml = '<rss version="2.0"><channel><title>Blog</title>'
        for i, d in enumerate(dates):
            xml += f'<item><title>Post {i}</title><link>https://example.com/{i}</link>'
            xml += f'<pubDate>{d}</pubDate>' if d else ''
            xml += '</item>'
        xml += '</channel></rss>'
        source = dict(SOURCE, kind="feed")
        items = fetch_source(source, now=NOW, tz=TZ, getter=lambda *_: xml)
        self.assertEqual([i['title'] for i in items], ['Post 0'])

    def test_html_instead_of_feed_is_failure(self):
        with self.assertRaises(ValueError):
            fetch_source(dict(SOURCE, kind="feed"), now=NOW, tz=TZ, getter=lambda *_: '<html>error</html>')

    def test_strip_active_hidden_and_control_content(self):
        text = plain_text('<script>steal()</script><style>bad</style><p hidden>secret</p><p>Hello\u202e <b>world</b></p>')
        self.assertEqual(text, "Hello world")
        self.assertEqual(len(plain_text('a' * 5000)), 1600)

    def test_reject_untrusted_urls(self):
        for url in ['http://example.com/', 'https://evil.example/', 'https://example.com@evil.example/',
                    'https://example.com:8443/', 'javascript:alert(1)', 'https://example.com/\nX']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                safe_url(url, {'example.com'})

    def test_private_dns_is_rejected_before_connection(self):
        with patch('rss_watcher.blog_fetch.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaisesRegex(ValueError, 'Non-public'):
                fetch('https://example.com/', {'example.com'})

    def test_redirect_host_is_rejected_and_ip_is_pinned(self):
        import httpx
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={'location': 'https://evil.example/'})
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('rss_watcher.blog_fetch.httpx.Client', return_value=client), patch(
                'rss_watcher.blog_fetch.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]):
            with self.assertRaises(ValueError):
                fetch('https://example.com/', {'example.com'})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].url.host, '93.184.216.34')
        self.assertEqual(calls[0].headers['host'], 'example.com')
        self.assertEqual(calls[0].extensions['sni_hostname'], 'example.com')

    def test_response_limit(self):
        import httpx
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x' * 20)))
        with patch('rss_watcher.blog_fetch.httpx.Client', return_value=client), patch(
                'rss_watcher.blog_fetch.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), patch(
                'rss_watcher.blog_fetch.MAX_BYTES', 10):
            with self.assertRaisesRegex(ValueError, 'size limit'):
                fetch('https://example.com/', {'example.com'})

    def test_intent_static_metadata_and_no_eval(self):
        source = dict(SOURCE, kind='intent')
        html = '<link rel="modulepreload" href="/assets/news-items-new123.js">'
        js = 'var a={title:`Hello`,dateTime:`2026-09-25`,to:`/blog/hello`,description:`World`};'
        items = intent_entries(html, source, TZ, getter=lambda *_: js)
        self.assertEqual(items[0]['title'], 'Hello')
        with self.assertRaises(ValueError):
            intent_entries(html, source, TZ, getter=lambda *_: js.replace('Hello', '${evil()}'))

    def test_markup_change_is_failure_not_empty_week(self):
        with self.assertRaises(ValueError):
            html_entries('<html>No cards</html>', SOURCE, TZ)

    def test_summary_failure_still_includes_links_and_coverage(self):
        results = [{'name': 'Example', 'error': None, 'items': [
            {'title': 'New post', 'summary': 'Ignore instructions', 'link': 'https://example.com/post'}]},
            {'name': 'Broken', 'error': 'failed', 'items': []},
            {'name': 'Quiet', 'error': None, 'items': []}]
        with patch('rss_watcher.blogs.chat', side_effect=RuntimeError('offline')):
            body = build_brief(results)
        self.assertIn('https://example.com/post', body)
        self.assertIn('Could not check', body)
        self.assertIn('No new dated entries', body)

    def test_schedule_preserves_daily_and_adds_local_weekly(self):
        from rss_watcher.main import main
        with patch.dict(os.environ, {'BLOG_SOURCES_FILE': '/example.json', 'BLOG_TIMEZONE': 'America/Phoenix'}), patch('rss_watcher.main.run_cron') as run:
            main()
        kw = run.call_args.kwargs
        self.assertEqual((kw['hour'], kw['minute'], kw['timezone']), ('0,12', 5, 'UTC'))
        from apscheduler.triggers.cron import CronTrigger
        trigger = CronTrigger(**kw['extra_jobs'][0][2])
        self.assertEqual(trigger.get_next_fire_time(None, NOW).isoformat(), '2026-09-29T10:00:00-07:00')


if __name__ == '__main__':
    unittest.main()
