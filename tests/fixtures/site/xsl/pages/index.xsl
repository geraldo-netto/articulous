<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" indent="yes"/>
  <xsl:template match="/index">
    <html lang="{translate(@lang, '_', '-')}">
      <head>
        <title><xsl:value-of select="@site"/> | <xsl:value-of select="@lang"/> | Page <xsl:value-of select="@page"/></title>
        <xsl:if test="starts-with(@self, 'https://') or starts-with(@self, 'http://')">
          <link rel="canonical" href="{@self}"/>
        </xsl:if>
      </head>
      <body>
        <ul>
          <xsl:for-each select="article">
            <li><a href="{url}"><xsl:value-of select="title"/></a></li>
          </xsl:for-each>
        </ul>
        <nav aria-label="Pagination">
          <xsl:if test="@previous != ''"><a rel="prev" href="{@previous}">Previous</a></xsl:if>
          <xsl:if test="@next != ''"><a rel="next" href="{@next}">Next</a></xsl:if>
        </nav>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
