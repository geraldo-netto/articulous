<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" indent="yes"/>
  <xsl:param name="articulous-url"/>
  <xsl:param name="articulous-lang"/>
  <xsl:param name="articulous-site"/>
  <xsl:param name="articulous-indexing" select="'index'"/>
  <xsl:param name="articulous-alternates"/>
  <xsl:param name="articulous-jsonld"/>
  <xsl:param name="articulous-title" select="article/title"/>
  <xsl:param name="articulous-description" select="article/description"/>
  <xsl:param name="articulous-author"/>
  <xsl:param name="articulous-image"/>
  <xsl:param name="articulous-published"/>
  <xsl:param name="articulous-modified"/>
  <xsl:template match="/article">
    <html lang="{translate($articulous-lang, '_', '-')}">
      <head>
        <xsl:value-of select="$articulous-alternates" disable-output-escaping="yes"/>
        <xsl:if test="$articulous-jsonld != ''">
          <script type="application/ld+json"><xsl:value-of select="$articulous-jsonld"/></script>
        </xsl:if>
        <xsl:if test="$articulous-indexing = 'noindex'"><meta name="robots" content="noindex"/></xsl:if>
        <title><xsl:value-of select="$articulous-title"/> | <xsl:value-of select="$articulous-site"/></title>
        <xsl:if test="normalize-space($articulous-description)">
          <meta name="description" content="{$articulous-description}"/>
        </xsl:if>
        <xsl:if test="starts-with($articulous-url, 'https://') or starts-with($articulous-url, 'http://')">
          <link rel="canonical" href="{$articulous-url}"/>
        </xsl:if>
      </head>
      <body>
        <h1><xsl:value-of select="$articulous-title"/></h1>
        <p><xsl:value-of select="$articulous-description"/></p>
        <xsl:if test="$articulous-author != ''"><p class="author"><xsl:value-of select="$articulous-author"/></p></xsl:if>
        <xsl:if test="$articulous-image != ''"><img src="{$articulous-image}" alt=""/></xsl:if>
        <xsl:if test="$articulous-published != ''"><time class="published" datetime="{$articulous-published}"><xsl:value-of select="$articulous-published"/></time></xsl:if>
        <xsl:if test="$articulous-modified != ''"><time class="modified" datetime="{$articulous-modified}"><xsl:value-of select="$articulous-modified"/></time></xsl:if>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
