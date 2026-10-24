<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:exsl="http://exslt.org/common" version="1.0"><xsl:template match="@*|node()" mode="content" priority="-1"><xsl:copy><xsl:apply-templates select="@*|node()" mode="content"/></xsl:copy></xsl:template>
  <xsl:template name="render-paragraph">
    <xsl:param name="paragraph-class" select="''"/><xsl:variable name="blocks" select="descendant::*[contains('|address|article|aside|blockquote|details|dialog|div|dl|fieldset|figcaption|figure|footer|form|h1|h2|h3|h4|h5|h6|header|hgroup|hr|iframe|main|menu|nav|ol|p|pre|section|table|ul|',concat('|',translate(local-name(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'|'))]"/>
    <xsl:choose><xsl:when test="$blocks">
      <div class="{$paragraph-class} {@class}"><xsl:apply-templates select="@*[name()!='class']|node()" mode="content"/></div>
    </xsl:when><xsl:otherwise><xsl:copy><xsl:apply-templates select="@*|node()" mode="content"/></xsl:copy></xsl:otherwise></xsl:choose>
  </xsl:template>
  <xsl:template match="comment()" mode="content"/>
  <xsl:template match="*[contains('|script|style|base|meta|link|object|embed|animate|set|animatemotion|animatetransform|discard|',concat('|',translate(local-name(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'|'))]" mode="content"/>
  <xsl:template match="@*" mode="content">
    <xsl:param name="attribute" select="name()"/>
    <xsl:variable name="name" select="translate(local-name(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"/>
    <xsl:variable name="allowed"><xsl:call-template name="content-attribute-allowed"><xsl:with-param name="name" select="$name"/></xsl:call-template></xsl:variable>
    <xsl:if test="string($allowed)='yes'">
      <xsl:attribute name="{$attribute}" namespace="{namespace-uri()}"><xsl:value-of select="."/></xsl:attribute>
    </xsl:if>
  </xsl:template>
  <xsl:template name="content-attribute-allowed">
    <xsl:param name="name"/>
    <xsl:choose>
      <xsl:when test="starts-with($name,'on') or contains('|style|srcdoc|',concat('|',$name,'|'))"/>
      <xsl:when test="$name='width' or $name='height'"><xsl:call-template name="content-image-dimension-allowed"/></xsl:when>
      <xsl:when test="contains('|href|src|action|formaction|poster|',concat('|',$name,'|'))"><xsl:call-template name="content-url-allowed"><xsl:with-param name="name" select="$name"/></xsl:call-template></xsl:when>
      <xsl:otherwise>yes</xsl:otherwise>
    </xsl:choose>
  </xsl:template>
  <xsl:template name="content-image-dimension-allowed">
    <xsl:if test="namespace-uri()='' and namespace-uri(..)='' and translate(local-name(..),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='img' and string(.)!='' and translate(.,'0123456789','')=''">yes</xsl:if>
  </xsl:template>
  <xsl:template name="content-url-allowed">
    <xsl:param name="name"/>
    <xsl:variable name="value" select="translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ &#9;&#10;&#13;','abcdefghijklmnopqrstuvwxyz')"/>
    <xsl:choose>
      <xsl:when test="starts-with($value,'javascript:') or starts-with($value,'vbscript:')"/>
      <xsl:when test="starts-with($value,'data:')">
        <xsl:if test="$name='src' and translate(local-name(..),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='img' and starts-with($value,'data:image/')">yes</xsl:if>
      </xsl:when>
      <xsl:otherwise>yes</xsl:otherwise>
    </xsl:choose>
  </xsl:template>
  <xsl:template name="render-code-block">
    <xsl:param name="error-label"/><xsl:param name="success-label"/><xsl:param name="copy-label"/><pre tabindex="0" data-toolbar-order="copy-to-clipboard">
      <xsl:attribute name="data-prismjs-copy"><xsl:value-of select="$copy-label"/></xsl:attribute>
      <xsl:attribute name="data-prismjs-copy-success"><xsl:value-of select="$success-label"/></xsl:attribute>
      <xsl:attribute name="data-prismjs-copy-error"><xsl:value-of select="$error-label"/></xsl:attribute>
      <xsl:apply-templates select="@*[translate(local-name(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')!='tabindex']" mode="content"/>
      <xsl:variable name="code-content"><xsl:choose>
        <xsl:when test="count(*)=1 and code and not(text()[normalize-space()])"><xsl:apply-templates select="code" mode="content"/></xsl:when>
        <xsl:otherwise><xsl:apply-templates select="node()" mode="content"/></xsl:otherwise>
      </xsl:choose></xsl:variable>
      <xsl:variable name="skip"><xsl:call-template name="code-leading-offset"><xsl:with-param name="text" select="string($code-content)"/></xsl:call-template></xsl:variable>
      <xsl:call-template name="code-trim-start"><xsl:with-param name="nodes" select="exsl:node-set($code-content)/node()"/><xsl:with-param name="skip" select="number($skip)"/></xsl:call-template>
    </pre>
  </xsl:template>
  <xsl:template match="pre//br" mode="content"><xsl:text>
</xsl:text></xsl:template>
  <xsl:template name="code-leading-offset">
    <xsl:param name="text"/>
    <xsl:variable name="leading"><xsl:choose>
      <xsl:when test="normalize-space($text)=''"><xsl:value-of select="$text"/></xsl:when>
      <xsl:otherwise><xsl:value-of select="substring-before($text,substring(normalize-space($text),1,1))"/></xsl:otherwise>
    </xsl:choose></xsl:variable>
    <xsl:call-template name="code-last-newline"><xsl:with-param name="text" select="string($leading)"/></xsl:call-template>
  </xsl:template>
  <xsl:template name="code-last-newline">
    <xsl:param name="text"/>
    <xsl:param name="offset" select="0"/>
    <xsl:variable name="half" select="floor(string-length($text) div 2)"/>
    <xsl:choose>
      <xsl:when test="not(contains($text,'&#10;'))">0</xsl:when>
      <xsl:when test="string-length($text)=1"><xsl:value-of select="$offset + 1"/></xsl:when>
      <xsl:when test="contains(substring($text,$half + 1),'&#10;')">
        <xsl:call-template name="code-last-newline">
          <xsl:with-param name="text" select="substring($text,$half + 1)"/>
          <xsl:with-param name="offset" select="$offset + $half"/>
        </xsl:call-template>
      </xsl:when>
      <xsl:otherwise><xsl:call-template name="code-last-newline">
        <xsl:with-param name="text" select="substring($text,1,$half)"/>
        <xsl:with-param name="offset" select="$offset"/>
      </xsl:call-template></xsl:otherwise>
    </xsl:choose>
  </xsl:template>
  <xsl:template name="code-trim-start">
    <xsl:param name="nodes"/>
    <xsl:param name="skip"/>
    <xsl:choose>
      <xsl:when test="$skip &lt;= 0"><xsl:copy-of select="$nodes"/></xsl:when>
      <xsl:when test="count($nodes) &gt; 1"><xsl:call-template name="code-trim-parts">
        <xsl:with-param name="nodes" select="$nodes"/><xsl:with-param name="skip" select="$skip"/>
      </xsl:call-template></xsl:when>
      <xsl:otherwise><xsl:for-each select="$nodes">
        <xsl:choose>
          <xsl:when test="self::text()"><xsl:value-of select="substring(.,$skip + 1)"/></xsl:when>
          <xsl:otherwise><xsl:copy><xsl:copy-of select="@*"/><xsl:call-template name="code-trim-start"><xsl:with-param name="nodes" select="node()"/><xsl:with-param name="skip" select="$skip"/></xsl:call-template></xsl:copy></xsl:otherwise>
        </xsl:choose>
      </xsl:for-each></xsl:otherwise>
    </xsl:choose>
  </xsl:template>
  <xsl:template name="code-trim-parts">
    <xsl:param name="nodes"/><xsl:param name="skip"/>
    <xsl:variable name="half" select="floor(count($nodes) div 2)"/>
    <xsl:variable name="left"><xsl:copy-of select="$nodes[position() &lt;= $half]"/></xsl:variable>
    <xsl:call-template name="code-trim-start">
      <xsl:with-param name="nodes" select="exsl:node-set($left)/node()"/><xsl:with-param name="skip" select="$skip"/>
    </xsl:call-template>
    <xsl:call-template name="code-trim-start">
      <xsl:with-param name="nodes" select="$nodes[position() &gt; $half]"/><xsl:with-param name="skip" select="$skip - string-length($left)"/>
    </xsl:call-template>
  </xsl:template>
  </xsl:stylesheet>
