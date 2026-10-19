"""Explicitly invoked OpenAI-compatible provider; never starts a model server."""
from dataclasses import dataclass
import json
import urllib.error
import urllib.request


@dataclass(frozen=True)
class HttpProvider:
    endpoint: str
    model: str
    temperature: float = 0.2
    timeout: int = 900

    @property
    def identity(self):
        return ('openai-compatible', self.endpoint.rstrip('/'), self.model, self.temperature)

    def post(self, system, user):
        payload = json.dumps({'model': self.model, 'messages': [
            {'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            'temperature': self.temperature, 'stream': False}).encode()
        request = urllib.request.Request(self.endpoint.rstrip('/') + '/v1/chat/completions',
                                        data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
            content = body['choices'][0]['message']['content']
            if not isinstance(content, str):
                raise TypeError('Message content must be text')
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise urllib.error.URLError('Invalid translation response') from error
        return content.strip()
