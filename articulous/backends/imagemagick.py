"""Explicit ImageMagick/optipng process adapter; never installs tools."""
from pathlib import Path
import subprocess
import tempfile

from ..filesystem import private_directory
from ..image_contracts import KINDS, validate_options


class ImageMagick:
    def dimensions(self, path: Path) -> tuple[int, int]:
        out = subprocess.run(['identify', '-format', '%w %h', str(path) + '[0]'],
                             capture_output=True, text=True, check=True).stdout.split()
        return int(out[0]), int(out[1])

    def shrink(self, path: Path, target: Path, largest: int, quality: int) -> None:
        validate_options(largest, quality)
        kind = KINDS[path.suffix.lower()]
        resize = f'{largest}x{largest}>'
        if kind == 'jpeg':
            subprocess.run(['convert', str(path), '-auto-orient', '-resize', resize, '-strip',
                            '-interlace', 'Plane', '-quality', str(quality), str(target)], check=True)
        else:
            subprocess.run(['convert', str(path), '-resize', resize, '-strip', str(target)], check=True)
            subprocess.run(['optipng', '-quiet', '-o2', str(target)], check=True)

    def workspace(self):
        return private_directory(Path(tempfile.gettempdir()))
