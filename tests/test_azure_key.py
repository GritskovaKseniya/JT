import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from jt import azure_key  # noqa: E402

GOOD = {'subscription_key': 'B' * 84, 'endpoint': 'https://api.cognitive.microsofttranslator.com', 'location': 'italynorth'}


class KeyCheckTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, 'azure_services.json')

    def put(self, data, raw=None):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(raw if raw is not None else json.dumps(data))
        return azure_key.problem(self.path)

    def test_a_good_key_is_accepted_whatever_the_length_of_the_azure_key(self):
        self.assertEqual(self.put(GOOD), '')
        self.assertEqual(self.put({**GOOD, 'subscription_key': 'c' * 32}), '')

    def test_the_file_is_missing(self):
        self.assertEqual(azure_key.problem(self.path), 'the key file was not found')

    def test_the_file_is_not_json_or_not_an_object(self):
        self.assertEqual(self.put(None, raw='{not json'), 'the key file cannot be read')
        self.assertEqual(self.put(None, raw=''), 'the key file cannot be read')
        self.assertEqual(self.put(['a']), 'the key file is not valid')

    def test_a_field_is_missing_or_empty_or_not_text(self):
        for field in azure_key.FIELDS:
            with self.subTest(field=field):
                self.assertEqual(self.put({k: v for k, v in GOOD.items() if k != field}), f'the key file has no {field}')
                self.assertEqual(self.put({**GOOD, field: '  '}), f'the key file has no {field}')
                self.assertEqual(self.put({**GOOD, field: 5}), f'the key file has no {field}')

    def test_the_placeholder_of_the_package_is_not_a_key(self):
        reason = self.put({**GOOD, 'subscription_key': 'INSERISCI-QUI-LA-CHIAVE-AZURE'})
        self.assertEqual(reason, 'the key is still the placeholder of the package')

    def test_a_key_with_the_wrong_shape_is_refused(self):
        for key in ('corta', 'con spazi dentro ' * 3, 'x' * 19, 'a' * 30 + '-' + 'b' * 30):
            with self.subTest(key=key):
                self.assertEqual(self.put({**GOOD, 'subscription_key': key}), 'the key does not look like an Azure key')

    def test_the_endpoint_must_be_https(self):
        self.assertEqual(self.put({**GOOD, 'endpoint': 'http://x.example'}), 'the endpoint is not an https address')
        self.assertEqual(self.put({**GOOD, 'endpoint': 'x.example'}), 'the endpoint is not an https address')

    def test_the_message_says_what_to_do(self):
        text = azure_key.message('the key file was not found', 'C:/x/AppData/Local/JT')
        self.assertTrue(text.startswith('No Azure key (the key file was not found).'))
        self.assertIn('Ask Kseniia Hrytskova', text)
        self.assertIn('C:/x/AppData/Local/JT', text)


if __name__ == '__main__':
    unittest.main()
