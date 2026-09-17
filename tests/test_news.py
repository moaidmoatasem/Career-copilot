from datetime import datetime, timezone
from email.utils import format_datetime

import pytest

from career_copilot.config import ConfigError, load_profile
from career_copilot.news import NewsError, fetch_feed, parse_feed

NOW = format_datetime(datetime.now(timezone.utc))
RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Playwright 2.0 brings new test automation tricks</title><link>https://example.com/pw</link>
<pubDate>{NOW}</pubDate><description>&lt;p&gt;Big release&lt;/p&gt;</description></item>
<item><title>Gardening tips</title><link>https://example.com/garden</link><pubDate>{NOW}</pubDate>
<description>Nothing to do with testing</description></item>
</channel></rss>""".encode()

ATOM = f"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>a</title>
<entry><title>AI testing in practice</title><link rel="alternate" href="https://example.com/ai"/>
<updated>{datetime.now(timezone.utc).isoformat()}</updated><summary>Evaluating LLM apps</summary></entry>
</feed>""".encode()


def test_parse_rss_and_atom():
    rss = parse_feed(RSS, "Example")
    assert [i["title"] for i in rss][0].startswith("Playwright")
    assert rss[0]["summary"] == "Big release"
    atom = parse_feed(ATOM, "Atom")
    assert atom[0]["url"] == "https://example.com/ai"


def test_refresh_and_digest_rank_by_interest(cp):
    cp.fetch_feed = lambda url: RSS
    result = cp.refresh_news()
    assert result["feeds"][0]["new"] == 2
    digest = cp.news_digest()
    assert digest["items"][0]["title"].startswith("Playwright")
    assert "playwright" in digest["items"][0]["matched_interests"]


def test_feed_errors_are_reported_per_feed(cp):
    def boom(url):
        raise OSError("network down")
    cp.fetch_feed = boom
    assert "network down" in cp.refresh_news()["feeds"][0]["error"]


def test_only_https_feeds(tmp_path):
    with pytest.raises(NewsError):
        fetch_feed("http://example.com/feed")
    profile = tmp_path / "p.toml"
    profile.write_text('[[news.feeds]]\nname = "x"\nurl = "http://example.com/feed"\n')
    with pytest.raises(ConfigError):
        load_profile(profile)
