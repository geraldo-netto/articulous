"""Independent golden control shapes for the scoped XSLT/XPath metric."""
from .complexity_xslt_contracts import XSL, XPathDecisions

XPATH_CASES = (
    ('simple', 'a/b', 0, 0), ('boolean', 'a and b or c', 2, 0),
    ('keyword-names', '@and or $and', 1, 0),
    ('literal-tokens', 'contains("and or [", "and")', 0, 0),
    ('literal-lines', 'contains("line\n  AND\n  PREDICATE", "text")', 0, 0),
    ('nested-predicates', 'a[b[c]]', 0, 2), ('successive-predicates', 'a[b][c]', 0, 2),
    ('filter', '(a|b)[true()][false()]', 0, 2), ('union', 'a|b', 0, 0),
    ('qualified-names', 'ns:and and ns:or', 1, 0),
    ('comparison', 'a != b and c > 1', 1, 0), ('arithmetic', '1 + 2 * 3 div 4 mod 2', 0, 0),
)
TEMPLATE_CASES = (
    ('straight', '<out/>', 1),
    ('boolean', '<xsl:if test="a and b or c"><out/></xsl:if>', 4),
    ('choose', '<xsl:choose><xsl:when test="a"/><xsl:when test="b"/><xsl:otherwise/></xsl:choose>', 3),
    ('loop', '<xsl:for-each select="a[b]"><xsl:value-of select="c"/></xsl:for-each>', 3),
    ('avt', '<out value="{{literal}} {a[b] and c}"/>', 3),
    ('quoted-braces', '''<out value="{contains('}', '{')}"/>''', 1),
    ('computed-name', '''<xsl:element name="{'out'}"/>''', 1),
    ('threshold', '<xsl:if test="a and b and c and d and e and f and g and h"/>', 9),
)


def stylesheet(body):
    return (f'<xsl:stylesheet xmlns:xsl="{XSL}" version="1.0">'
            f'<xsl:template match="/">{body}</xsl:template></xsl:stylesheet>').encode()


def calibrate(compiler, measure):
    xpath, templates = [], []
    for name, source, booleans, predicates in XPATH_CASES:
        actual = compiler(source)
        if (actual.booleans, actual.predicates) != (booleans, predicates):
            raise ValueError('Failed native XPath calibration: ' + name)
        xpath.append({'name': name, 'source': source, 'expected': [booleans, predicates],
                      'actual': [actual.booleans, actual.predicates], 'version': actual.compiler_version,
                      'trace_sha256': actual.trace_sha256})
    for name, body, expected in TEMPLATE_CASES:
        actual = measure(stylesheet(body), compiler)[0]['complexity']
        if actual != expected:
            raise ValueError('Failed XSLT control calibration: ' + name)
        templates.append({'name': name, 'body': body, 'expected': expected, 'actual': actual})
    return {'xpath': xpath, 'templates': templates}


def check_calibration(calibration):
    xpath = calibration['xpath']
    identities = [(row['name'], row['source'], *row['expected']) for row in xpath]
    if tuple(identities) != XPATH_CASES:
        raise ValueError('Incomplete XPath calibration')
    versions = set()
    for row in xpath:
        if row['actual'] != row['expected']:
            raise ValueError('Failed recorded XPath calibration')
        result = XPathDecisions(row['actual'][0], row['actual'][1], row['version'], row['trace_sha256'])
        versions.add(result.compiler_version)
    if len(versions) != 1:
        raise ValueError('Native XPath compiler changed during calibration')
    check_template_calibration(calibration['templates'])
    return versions.pop()


def check_template_calibration(rows):
    identities = [(row['name'], row['body'], row['expected']) for row in rows]
    if tuple(identities) != TEMPLATE_CASES:
        raise ValueError('Incomplete XSLT calibration')
    if any(row['actual'] != row['expected'] for row in rows):
        raise ValueError('Failed recorded XSLT calibration')
