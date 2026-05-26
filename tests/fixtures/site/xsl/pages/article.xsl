<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" indent="yes"/>
  <xsl:template match="/article">
    <html>
      <head><title><xsl:value-of select="title"/></title></head>
      <body>
        <h1><xsl:value-of select="title"/></h1>
        <p><xsl:value-of select="description"/></p>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
