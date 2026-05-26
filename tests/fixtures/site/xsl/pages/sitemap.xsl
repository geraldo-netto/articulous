<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="xml" indent="yes"/>
  <xsl:template match="/sitemap">
    <urlset>
      <xsl:for-each select="url">
        <url><loc><xsl:value-of select="."/></loc></url>
      </xsl:for-each>
    </urlset>
  </xsl:template>
</xsl:stylesheet>
