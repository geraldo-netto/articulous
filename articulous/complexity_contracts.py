"""Source-independent schema and admission bounds for complexity evidence."""
from dataclasses import dataclass
import re

MAX_EVIDENCE_BYTES = 32 * 1024 * 1024


def require_digest(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('Invalid complexity source digest')


def require_relative(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Invalid complexity source path')
    if any(part in ('', '.', '..') for part in value.split('/')) or '\\' in value or ':' in value:
        raise ValueError('Invalid complexity source path')


def require_position(line, column):
    if type(line) is not int or type(column) is not int or line < 1 or column < 0:
        raise ValueError('Invalid complexity source position')


@dataclass(frozen=True)
class FunctionMeasurement:
    name: str
    line: int
    column: int
    end_line: int
    end_column: int
    body_sha256: str
    projection_sha256: str
    complexity: int

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError('Invalid complexity function name')
        require_position(self.line, self.column)
        require_position(self.end_line, self.end_column)
        if (self.end_line, self.end_column) <= (self.line, self.column):
            raise ValueError('Invalid complexity function boundary')
        require_digest(self.body_sha256)
        require_digest(self.projection_sha256)
        if type(self.complexity) is not int or self.complexity < 1:
            raise ValueError('Invalid function complexity')


def decode_function(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid complexity function record')
    try:
        return FunctionMeasurement(**value)
    except TypeError as error:
        raise ValueError('Invalid complexity function fields') from error
