import unittest
from jt.layers import BY_NAME, VISIBLE, layer_of_code, layer_of_name

class LayerOfCodeTest(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(layer_of_code(2999999).name, 'AP')
        self.assertEqual(layer_of_code(3000000).name, 'CT')
        self.assertEqual(layer_of_code(3999999).name, 'CT')
        self.assertEqual(layer_of_code(4000000).name, 'CW')
        self.assertEqual(layer_of_code(4999999).name, 'CW')
        self.assertEqual(layer_of_code(5000000).name, 'CK')
        self.assertEqual(layer_of_code(5999999).name, 'CK')
        self.assertEqual(layer_of_code(9000000).name, 'CC')

    def test_code_out_of_range(self):
        with self.assertRaises(ValueError):
            layer_of_code(5)

class LayerOfNameTest(unittest.TestCase):
    def test_layer_of_name(self):
        # Test cases for layer_of_name function
        self.assertEqual(layer_of_name('CtDescrizione').name, 'CT')
        self.assertEqual(layer_of_name('CwXxx').name, 'CW')
        self.assertEqual(layer_of_name('CkAbc').name, 'CK')
        self.assertEqual(layer_of_name('CcAbc').name, 'CC')
        self.assertEqual(layer_of_name('FwSomething').name, 'FW')
        self.assertEqual(layer_of_name('Qualcosa').name, 'AP')  # No prefix

    def test_layer_of_name_invalid(self):
        with self.assertRaises(ValueError):
            layer_of_name('')

    def test_wrong_case_is_not_a_layer(self):
        self.assertIsNone(layer_of_name('ctDescrizione'))
        self.assertIsNone(layer_of_name('CTDescrizione'))

class VisibleTest(unittest.TestCase):
    def test_visible_are_known_layers(self):
        for name in VISIBLE:
            self.assertIn(name, BY_NAME)


class LevelTitlesTests(unittest.TestCase):
    def test_titles_are_written_out_and_short_labels_stay_short(self):
        from jt.layers import DEFAULT_LEVEL, LEVEL_ALL, LEVEL_CHOICES, level_label, level_title
        self.assertEqual(list(LEVEL_CHOICES), ['All levels', 'Standard', 'CW - Integrations', 'CT - Customizations',
                                              'CC - Client Customization'])
        self.assertEqual([LEVEL_CHOICES[t] and LEVEL_CHOICES[t].name for t in LEVEL_CHOICES], [None, 'AP', 'CW', 'CT', 'CC'])
        self.assertEqual(LEVEL_ALL, 'All levels')
        self.assertEqual(DEFAULT_LEVEL, 'Standard')
        self.assertEqual([level_label(BY_NAME[n]) for n in ('AP', 'CW', 'CT', 'CK')], ['Standard', 'CW', 'CT', 'CK'])
        self.assertEqual(level_title(BY_NAME['CK']), 'CK')                  # senza titolo esteso: il nome

    def test_only_visible_levels_are_choices(self):
        from jt.layers import LEVEL_CHOICES
        self.assertNotIn('CK', LEVEL_CHOICES)
        self.assertEqual({layer.name for layer in LEVEL_CHOICES.values() if layer}, set(VISIBLE))
