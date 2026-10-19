"""Optional content/code resources, with one packaged source for every published byte."""
from importlib.resources import files
import json


from .resource_contracts import ResourceFile


def code_resources():
    root = files('articulous').joinpath('theme_assets')
    resources = [ResourceFile(path, root.joinpath(path).read_bytes()) for path in prism_provenance()['files']]
    resources.append(ResourceFile('assets/js/code-blocks.js', root.joinpath('assets/js/code-blocks.js').read_bytes()))
    resources.append(ResourceFile('xsl/components/articulous/content.xsl', root.joinpath('xsl/content.xsl').read_bytes()))
    return tuple(resources)


def prism_provenance():
    root = files('articulous').joinpath('theme_assets')
    return json.loads(root.joinpath('third_party/prism/manifest.json').read_text())


def search_resources():
    root = files('articulous').joinpath('theme_assets')
    return (ResourceFile('assets/js/search-client.js', root.joinpath('assets/js/search-client.js').read_bytes()),)
