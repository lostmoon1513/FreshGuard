from datetime import UTC, datetime

from app.engine.providers.html_text import extract_page, normalize_text

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def page(body="", head=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


def test_text_title_and_block_structure():
    html = page(
        "<h1>Big News</h1><p>First  paragraph\n with   spaces.</p>"
        "<ul><li>One</li><li>Two</li></ul>",
        "<title> My  Page </title>",
    )
    result = extract_page(html, NOW)
    assert result.title == "My Page"
    assert result.text == "Big News\nFirst paragraph with spaces.\nOne\nTwo"


def test_scripts_styles_and_templates_are_dropped():
    html = page(
        "<script>var secret='x';</script><style>p{}</style><noscript>no js</noscript>"
        "<p>Visible</p><svg><text>icon</text></svg>"
    )
    assert extract_page(html, NOW).text == "Visible"


def test_self_closing_and_unclosed_tags_do_not_break_text():
    result = extract_page(page("a<br/>b<br>c<img src=x/><p>d"), NOW)
    assert result.text == "a\nb\nc\nd"


def test_entities_are_decoded():
    assert extract_page(page("<p>Tom &amp; Jerry &mdash; 5 &lt; 6</p>"), NOW).text == (
        "Tom & Jerry — 5 < 6"
    )


def test_malformed_html_never_raises():
    for html in ["", "<", "<<<>>>", "<p>unclosed <b>bold", "<script>never closed", "\x00\x01"]:
        extract_page(html, NOW)


def date_of(head):
    return extract_page(page("<p>x</p>", head), NOW).published_at


def test_meta_published_time():
    head = '<meta property="article:published_time" content="2026-10-05T08:30:00Z">'
    assert date_of(head) == datetime(2026, 10, 5, 8, 30, tzinfo=UTC)


def test_json_ld_beats_meta_tags():
    head = (
        '<meta name="date" content="2020-01-01">'
        '<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-09-01"}'
        "</script>"
    )
    assert date_of(head) == datetime(2026, 9, 1, tzinfo=UTC)


def test_json_ld_graph_and_lists():
    head = (
        '<script type="application/ld+json">{"@graph":[{"@type":"WebSite"},'
        '{"@type":"Article","datePublished":"2026-08-15T00:00:00+00:00"}]}</script>'
    )
    assert date_of(head) == datetime(2026, 8, 15, tzinfo=UTC)


def test_modified_dates_are_ignored_and_nothing_is_guessed_from_prose():
    head = (
        '<meta property="article:modified_time" content="2026-11-01">'
        '<meta property="og:updated_time" content="2026-11-02">'
    )
    assert date_of(head) is None
    html = page("<p>Published on March 3, 2026 by staff</p>")
    assert extract_page(html, NOW).published_at is None


def test_priority_order_and_unparseable_values_fall_through():
    head = (
        '<meta name="date" content="2019-05-05">'
        '<meta property="article:published_time" content="not a date">'
        '<meta name="pubdate" content="2026-07-07">'
    )
    assert date_of(head) == datetime(2026, 7, 7, tzinfo=UTC)


def test_time_tag_with_itemprop():
    html = page('<time itemprop="datePublished" datetime="2026-06-06">June 6</time>')
    assert extract_page(html, NOW).published_at == datetime(2026, 6, 6, tzinfo=UTC)


def test_broken_json_ld_is_ignored():
    head = (
        '<script type="application/ld+json">{not json</script>'
        '<meta name="date" content="2026-01-02">'
    )
    assert date_of(head) == datetime(2026, 1, 2, tzinfo=UTC)


def test_normalize_text():
    assert normalize_text("  a \t b \r\n\r\n\n c  ") == "a b\nc"