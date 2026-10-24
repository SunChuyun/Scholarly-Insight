"""Synthetic Atom responses shared by parser and API integration tests."""


def atom_feed(total=1, start=0, count=1):
    """Build small, synthetic arXiv responses for pagination and parsing tests."""
    entries = "".join(
        f"""
        <entry>
          <id>http://arxiv.org/abs/2601.{number:05d}v1</id>
          <title>A sample\n paper &amp; metadata</title>
          <author><name>Ana Example</name></author>
          <author><name>Ben Example</name></author>
          <summary>First line.\n Second line.</summary>
          <published>2026-01-01T12:00:00Z</published>
          <updated>2026-01-02T12:00:00Z</updated>
          <category term="cs.AI"/><category term="cs.CL"/>
          <link title="pdf" href="http://arxiv.org/pdf/2601.{number:05d}v1"/>
        </entry>"""
        for number in range(start, start + count)
    )
    return f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
        <opensearch:totalResults>{total}</opensearch:totalResults>
        <opensearch:startIndex>{start}</opensearch:startIndex>
        {entries}</feed>""".encode()
