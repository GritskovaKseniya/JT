"""Glossario: Glossary.prepare/restore e AzureTranslator con `post` iniettato."""
import os
import unittest

import helpers
from helpers import FakeAzure, JtCase, write_json, write_text
from jt.azure import AzureTranslator
from jt.glossary import Glossary, Prepared

SPAN = '<span class="notranslate">{}</span>'


class GlossaryCase(JtCase):
    def setUp(self):
        super().setUp()
        self.paths_ = self.paths()
        self.glossary = Glossary.load(self.paths_.glossary)
        self.azure = FakeAzure()
        self.translator = AzureTranslator(helpers.FAKE_AZURE, self.glossary, post=self.azure)

    def tr(self, text, lan_in='it', lan_out='de'):
        return self.translator.translate(text, lan_in, lan_out)


class ShippedGlossaryTests(GlossaryCase):
    def test_shipped_rules(self):
        self.assertEqual(self.glossary.replace['UMV'], 'HU')
        self.assertEqual(self.glossary.replace['Umv'], 'Hu')
        self.assertIn('it', self.glossary.replace_skip_targets)
        self.assertEqual(self.glossary.source_languages, [])
        for term in ('Supply Chain Planning', 'MES', 'MRP', 'JFlex', 'DF', 'Pegging'):
            self.assertIn(term, self.glossary.keep)


class PrepareTests(GlossaryCase):
    def test_exact_replace_term_needs_no_azure(self):
        self.assertEqual(self.glossary.prepare('it', 'fr', 'UMV'), Prepared('UMV', False, 'HU'))
        self.assertEqual(self.glossary.prepare('it', 'fr', '  UMV  ').direct, 'HU')

    def test_variant_umv_to_hu(self):
        self.assertEqual(self.glossary.prepare('it', 'fr', 'Umv').direct, 'Hu')
        prepared = self.glossary.prepare('it', 'fr', 'Il Umv qui')
        self.assertEqual(prepared.payload, 'Il ' + SPAN.format('Hu') + ' qui')

    def test_exact_keep_term_returned_as_is(self):
        self.assertEqual(self.glossary.prepare('it', 'fr', 'Supply Chain Planning'),
                         Prepared('Supply Chain Planning', False, 'Supply Chain Planning'))
        self.assertEqual(self.glossary.prepare('it', 'fr', '  MES ').direct, '  MES ')

    def test_term_inside_sentence_is_marked_notranslate(self):
        prepared = self.glossary.prepare('it', 'fr', 'Ordine UMV aperto')
        self.assertEqual(prepared, Prepared('Ordine ' + SPAN.format('HU') + ' aperto', True, None))

    def test_keep_term_inside_sentence_keeps_original_text(self):
        prepared = self.glossary.prepare('it', 'fr', 'Open Supply Chain Planning now')
        self.assertEqual(prepared.payload, 'Open ' + SPAN.format('Supply Chain Planning') + ' now')
        self.assertTrue(prepared.html)

    def test_longest_term_wins(self):
        prepared = self.glossary.prepare('it', 'fr', 'I Business Partners sono')
        self.assertEqual(prepared.payload, 'I ' + SPAN.format('Business Partners') + ' sono')

    def test_adjacent_terms(self):
        prepared = self.glossary.prepare('it', 'fr', 'UMV MES')
        self.assertEqual(prepared.payload, SPAN.format('HU') + ' ' + SPAN.format('MES'))

    def test_special_chars_are_escaped_when_html(self):
        prepared = self.glossary.prepare('it', 'fr', 'UMV & a < b > c')
        self.assertEqual(prepared.payload, SPAN.format('HU') + ' &amp; a &lt; b &gt; c')
        self.assertTrue(prepared.html)

    def test_text_without_terms_is_untouched_and_not_html(self):
        self.assertEqual(self.glossary.prepare('it', 'fr', 'a & b < c'), Prepared('a & b < c', False, None))

    def test_whole_word_only(self):
        for text in ('UMVX', 'UMV_ID', 'xUMV', 'MESSAGGIO', 'Prima9UMV'):
            self.assertEqual(self.glossary.prepare('it', 'fr', text), Prepared(text, False, None), text)

    def test_any_source_language(self):
        self.assertEqual(self.glossary.prepare('de', 'es', 'Supply Chain Planning').direct, 'Supply Chain Planning')
        self.assertEqual(self.glossary.prepare('de', 'es', 'UMV').direct, 'HU')
        self.assertIn(SPAN.format('MRP'), self.glossary.prepare('de', 'es', 'Der MRP Lauf').payload)

    def test_target_italian_skips_replace_but_keeps_terms(self):
        self.assertEqual(self.glossary.prepare('en', 'it', 'UMV'), Prepared('UMV', False, None))
        self.assertEqual(self.glossary.prepare('en', 'it', 'Open UMV now'), Prepared('Open UMV now', False, None))
        self.assertEqual(self.glossary.prepare('en', 'it', 'MES').direct, 'MES')
        prepared = self.glossary.prepare('en', 'it', 'Open MES and UMV')
        self.assertEqual(prepared.payload, 'Open ' + SPAN.format('MES') + ' and UMV')

    def test_source_languages_restriction(self):
        glossary = Glossary(replace={'UMV': 'HU'}, keep=['MES'], source_languages=['en'])
        self.assertEqual(glossary.prepare('de', 'fr', 'UMV'), Prepared('UMV', False, None))
        self.assertEqual(glossary.prepare('de', 'fr', 'Der MES'), Prepared('Der MES', False, None))
        self.assertEqual(glossary.prepare('en', 'fr', 'UMV').direct, 'HU')

    def test_missing_glossary_file_means_no_rules(self):
        glossary = Glossary.load(os.path.join(self.tmp, 'nope.json'))
        self.assertEqual((glossary.replace, glossary.keep, glossary.source_languages, glossary.replace_skip_targets),
                         ({}, [], [], []))
        self.assertEqual(glossary.prepare('it', 'de', 'UMV'), Prepared('UMV', False, None))

    def test_broken_glossary_file_means_no_rules(self):
        path = os.path.join(self.tmp, 'broken.json')
        write_text(path, '{not valid json')
        glossary = Glossary.load(path)
        self.assertEqual(glossary.prepare('it', 'de', 'UMV'), Prepared('UMV', False, None))

    def test_partial_glossary_file(self):
        path = os.path.join(self.tmp, 'partial.json')
        write_json(path, {'keep': ['XYZ']})
        glossary = Glossary.load(path)
        self.assertEqual(glossary.prepare('it', 'de', 'XYZ').direct, 'XYZ')
        self.assertEqual(glossary.replace, {})

    def test_non_string_text(self):
        for value in (None, 123, 4.5, ['UMV']):
            self.assertEqual(self.glossary.prepare('it', 'de', value), Prepared(value, False, None))

    def test_restore(self):
        self.assertEqual(Glossary.restore('A <span class="notranslate">HU</span> &amp; b &lt; c &gt; d'),
                         'A HU & b < c > d')
        self.assertEqual(Glossary.restore('plain'), 'plain')


class TranslatorTests(GlossaryCase):
    def test_exact_term_does_not_call_azure(self):
        self.assertEqual(self.tr('UMV', 'it', 'fr'), 'HU')
        self.assertEqual(self.tr('Supply Chain Planning', 'de', 'es'), 'Supply Chain Planning')
        self.assertEqual(self.azure.calls, [])

    def test_term_inside_sentence_is_marked_and_restored(self):
        result = self.tr('Ordine UMV aperto', 'it', 'de')
        call = self.azure.calls[0]
        self.assertEqual(call['text'], 'Ordine ' + SPAN.format('HU') + ' aperto')
        self.assertEqual(call['params']['textType'], 'html')
        self.assertEqual(result, 'T:Ordine HU aperto')

    def test_special_chars_round_trip(self):
        self.assertEqual(self.tr('UMV & a < b > c', 'it', 'de'), 'T:HU & a < b > c')

    def test_plain_text_is_sent_as_plain(self):
        result = self.tr('Nuovo testo', 'it', 'de')
        call = self.azure.calls[0]
        self.assertEqual(call['text'], 'Nuovo testo')
        self.assertNotIn('textType', call['params'])
        self.assertEqual(result, 'T:Nuovo testo')

    def test_plain_text_with_entities_is_not_unescaped(self):
        self.assertEqual(self.tr('a &amp; b', 'it', 'de'), 'T:a &amp; b')

    def test_request_shape(self):
        self.tr('Nuovo testo', 'de', 'fr')
        call = self.azure.calls[0]
        self.assertEqual(call['url'], 'https://azure.invalid/translate')
        self.assertEqual(call['params'], {'api-version': '3.0', 'from': 'de', 'to': ['fr']})
        self.assertEqual(call['headers']['Ocp-Apim-Subscription-Key'], 'FAKE-KEY')
        self.assertEqual(call['headers']['Ocp-Apim-Subscription-Region'], 'fakeland')
        self.assertTrue(call['headers']['X-ClientTraceId'])

    def test_target_italian_calls_azure_for_umv_but_keeps_terms(self):
        self.assertEqual(self.tr('UMV', 'en', 'it'), 'T:UMV')
        self.assertEqual(self.tr('MES', 'en', 'it'), 'MES')
        self.assertEqual(len(self.azure.calls), 1)

    def test_azure_error_propagates(self):
        self.translator = AzureTranslator(helpers.FAKE_AZURE, self.glossary, post=FakeAzure(fail_on='boom'))
        with self.assertRaises(RuntimeError):
            self.tr('boom', 'it', 'de')


if __name__ == '__main__':
    unittest.main()
