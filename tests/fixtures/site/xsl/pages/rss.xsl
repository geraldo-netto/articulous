<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="xml" indent="yes"/>
  <xsl:template match="/rss">
    <rss version="2.0">
      <channel>
        <title><xsl:value-of select="@site"/></title>
        <link>https://example.test/en/page/1/</link>
        <description>Recent articles from the Articulous test site.</description>
        <xsl:for-each select="item">
          <item>
            <title><xsl:value-of select="title"/></title>
            <link><xsl:value-of select="url"/></link>
          </item>
        </xsl:for-each>
      </channel>
    </rss>
  </xsl:template>
</xsl:stylesheet>
