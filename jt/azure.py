"""Client di Azure Translator (API v3.0)."""
import uuid

import requests

from .config import AZURE_TIMEOUT
from .glossary import Glossary


class AzureTranslator:
    def __init__(self, credentials, glossary, post=None, timeout=AZURE_TIMEOUT):
        """credentials: {subscription_key, endpoint, location}. `post` e' sostituibile nei test."""
        self._credentials = credentials
        self._glossary = glossary
        self._post = post
        self._timeout = timeout

    def translate(self, text, lan_in, lan_out):
        prepared = self._glossary.prepare(lan_in, lan_out, text)
        if prepared.direct is not None:
            return prepared.direct

        params = {'api-version': '3.0', 'from': lan_in, 'to': [lan_out]}
        if prepared.html:
            params['textType'] = 'html'
        headers = {
            'Ocp-Apim-Subscription-Key': self._credentials['subscription_key'],
            'Ocp-Apim-Subscription-Region': self._credentials['location'],
            'Content-type': 'application/json',
            'X-ClientTraceId': str(uuid.uuid4()),
        }
        post = self._post or requests.post
        response = post(f"{self._credentials['endpoint']}/translate", params=params, headers=headers,
                        json=[{'text': prepared.payload}], timeout=self._timeout).json()
        if isinstance(response, dict) and 'error' in response:
            error = response['error']
            raise RuntimeError(f"Azure error {error.get('code')}: {error.get('message')}")
        result = response[0]['translations'][0]['text']
        return Glossary.restore(result) if prepared.html else result
