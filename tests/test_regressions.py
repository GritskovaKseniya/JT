"""Regressioni: difetti trovati durante la revisione, ognuno con il suo test."""
import unittest

import helpers
from helpers import FakeAzure, FakeDriver, JtCase
from jt.azure import AzureTranslator
from jt.db import Database
from jt.glossary import Glossary
from jt.service import TranslationService
from jt.settings import Settings
from jt.tables import FieldStringsTable, get_table


class KeyParsingTests(unittest.TestCase):
    def test_digit_lookalikes_are_rejected_for_numeric_keys(self):
        # '²' e le cifre arabo-indiane passano str.isdigit() ma int() fallirebbe piu' avanti
        spec = get_table('FW_STRINGS')
        for bad in ('²', '١٢', '1²'):
            with self.assertRaises(ValueError, msg=repr(bad)):
                spec.parse_keys(bad)

    def test_option_names_must_be_ascii(self):
        with self.assertRaises(ValueError):
            get_table('FW_OPZIONI').parse_keys('Opzioneè')


class ToleranceTests(JtCase):
    def test_json_that_is_not_an_object_is_treated_as_empty(self):
        paths = self.paths()
        for content in ('[]', 'null', '"testo"', '5'):
            helpers.write_text(paths.glossary, content)
            helpers.write_text(paths.connection, content)
            helpers.write_text(paths.query, content)
            self.assertEqual(Glossary.load(paths.glossary), Glossary(), content)
            settings = Settings(paths)
            self.assertEqual(settings.connection(), dict.fromkeys(('host', 'port', 'sid', 'username', 'password'), ''))
            self.assertEqual(settings.last_query(), {})

    def test_saving_over_a_non_object_file_rewrites_it_as_an_object(self):
        paths = self.paths()
        helpers.write_text(paths.connection, '[]')
        Settings(paths).save_connection('h', '1', 's', 'u', 'p')
        self.assertEqual(Settings(paths).connection()['host'], 'h')


class LogOutputTests(unittest.TestCase):
    def test_field_strings_log_output_falls_back_to_caption_then_tip(self):
        spec = FieldStringsTable()
        translate = lambda text, required=False: None if text is None else 'T:' + text
        self.assertEqual(spec.translate_row(('it', 1, 'Cap', None, None), translate).primary, 'T:Cap')
        self.assertEqual(spec.translate_row(('it', 1, None, None, 'Tip'), translate).primary, 'T:Tip')
        self.assertEqual(spec.translate_row(('it', 1, 'Cap', 'Desc', 'Tip'), translate).primary, 'T:Desc')


class BlankTextTests(JtCase):
    def test_blank_text_is_not_sent_to_azure_and_is_copied_as_is(self):
        driver = FakeDriver()
        driver.db.source = dict(driver.db.source, FW_STRINGS=[('it', 1, '   ', None, None, None),
                                                              ('it', 2, 'Ciao', None, None, None)])
        driver.db.missing = {'FW_STRINGS': 2}
        db = Database(driver)
        db.connect('h', '1521', 'S', 'u', 'p')
        service = TranslationService(db)
        azure = FakeAzure()
        translator = AzureTranslator(helpers.FAKE_AZURE, Glossary(), post=azure)
        selection = service.load_missing(get_table('FW_STRINGS'), 'it', 'en', 10)
        result = service.run(selection, translator)
        self.assertEqual([call['text'] for call in azure.calls], ['Ciao'])      # lo spazio non va ad Azure
        self.assertEqual(result.inserts, 2)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(driver.db.inserts()[0][1], ['en', 1, '   ', None])


if __name__ == '__main__':
    unittest.main()
