<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" indent="yes"/>
  <xsl:param name="articulous-url"/>
  <xsl:param name="articulous-lang"/>
  <xsl:param name="articulous-site"/>
  <xsl:param name="articulous-indexing" select="'index'"/>
  <xsl:param name="articulous-alternates"/>
  <xsl:template match="/article">
    <html lang="{translate($articulous-lang, '_', '-')}">
      <head>
        <xsl:value-of select="$articulous-alternates" disable-output-escaping="yes"/>
        <xsl:if test="$articulous-indexing = 'noindex'"><meta name="robots" content="noindex"/></xsl:if>
        <title><xsl:value-of select="title"/> | <xsl:value-of select="$articulous-site"/></title>
        <xsl:if test="normalize-space(description)">
          <meta name="description" content="{description}"/>
        </xsl:if>
        <xsl:if test="starts-with($articulous-url, 'https://') or starts-with($articulous-url, 'http://')">
          <link rel="canonical" href="{$articulous-url}"/>
        </xsl:if>
      </head>
      <body>
        <h1><xsl:value-of select="title"/></h1>
        <p><xsl:value-of select="description"/></p>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
