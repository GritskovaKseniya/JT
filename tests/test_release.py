"""I controlli della procedura di rilascio (tools/release.py): non si costruisce niente, si provano solo le funzioni."""
import os
import sys
import unittest
import zipfile

import helpers
from helpers import JtCase

sys.path.insert(0, os.path.join(helpers.ROOT, 'tools'))
import build  # noqa: E402
import release  # noqa: E402

GOOD = {name: b'x' for name in release.PACKAGE_FILES}
GOOD['JT/Data/azure_services.json'] = b'{"subscription_key": "abcdef0123456789abcdef0123456789"}'
GOOD['JT/Graphics/icons/bubbles.ico'] = b'ico'
GOOD['JT/_internal/base_library.zip'] = b'zip'


class CheckZipTests(JtCase):
    def make(self, files):
        path = os.path.join(self.tmp, 'JT.zip')
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in files.items():
                z.writestr(name, data)
        return path

    def test_a_good_package_has_no_problems(self):
        self.assertEqual(release.check_zip(self.make(GOOD)), [])

    def test_a_missing_file_is_reported(self):
        files = {k: v for k, v in GOOD.items() if k != 'JT/LEGGIMI.txt'}
        self.assertEqual(release.check_zip(self.make(files)), ['manca JT/LEGGIMI.txt'])

    def test_a_missing_icon_is_reported(self):
        files = {k: v for k, v in GOOD.items() if not k.endswith('.ico')}
        self.assertEqual(release.check_zip(self.make(files)), ["manca l'icona (Graphics/icons)"])

    def test_personal_files_never_travel(self):
        for name in ('JT/Data/connection_data.json', 'JT/query_data.json', 'JT/Logs/JT_errors_log_1.csv', 'JT/x.csv'):
            with self.subTest(name=name):
                problems = release.check_zip(self.make({**GOOD, name: b'secret'}))
                self.assertEqual(problems, [f'file che non deve esserci: {name}'])

    def test_the_test_db_tool_and_the_developer_readme_are_not_in_the_colleagues_package(self):
        for name in ('JT/JT-TestDB.exe', 'JT/README.md'):
            problems = release.check_zip(self.make({**GOOD, name: b'x'}))
            self.assertEqual(problems, [f'file che non deve esserci: {name}'])

    def test_library_files_with_innocent_names_are_not_flagged(self):
        files = {**GOOD, 'JT/_internal/some_lib/README.md': b'x', 'JT/_internal/dist-info/data.json': b'x'}
        self.assertEqual(release.check_zip(self.make(files)), [])

    def test_the_azure_key_must_be_real_when_it_is_meant_to_be_included(self):
        files = {**GOOD, 'JT/Data/azure_services.json': release.PLACEHOLDER_KEY.encode()}
        self.assertEqual(release.check_zip(self.make(files)), ["la chiave Azure e' ancora il segnaposto"])

    def test_the_azure_key_must_not_be_there_when_it_is_not_meant_to_be(self):
        problems = release.check_zip(self.make(GOOD), with_azure=False)
        self.assertEqual(problems, ["la chiave Azure e' dentro il pacchetto ma non doveva esserci"])
        files = {**GOOD, 'JT/Data/azure_services.json': release.PLACEHOLDER_KEY.encode()}
        self.assertEqual(release.check_zip(self.make(files), with_azure=False), [])


class BumpVersionTests(JtCase):
    def test_only_the_version_line_changes_and_the_old_one_is_returned(self):
        path = os.path.join(self.tmp, 'config.py')
        with open(path, 'w', newline='') as f:
            f.write("APP = 'x'\r\nVERSION = '3.0'\r\nOTHER = '3.0'\r\n")
        self.assertEqual(release.bump_version(path, '3.1'), '3.0')
        with open(path, newline='') as f:
            self.assertEqual(f.read(), "APP = 'x'\r\nVERSION = '3.1'\r\nOTHER = '3.0'\r\n")

    def test_a_config_without_version_is_an_error(self):
        path = os.path.join(self.tmp, 'config.py')
        with open(path, 'w') as f:
            f.write("APP = 'x'\n")
        with self.assertRaises(ValueError):
            release.bump_version(path, '3.1')

    def test_the_real_config_has_a_version_line(self):
        from jt.config import VERSION
        self.assertRegex(VERSION, r'^\d+\.\d+')
        with open(os.path.join(helpers.ROOT, 'jt', 'config.py'), encoding='utf-8') as f:
            self.assertRegex(f.read(), r"(?m)^VERSION = '[^']*'")


if __name__ == '__main__':
    unittest.main()


class CleaningDistTests(JtCase):
    """Costruire una versione nuova non cancella gli .zip e i setup delle versioni precedenti."""

    def make(self, *names):
        folder = os.path.join(self.tmp, 'dist')
        os.makedirs(folder)
        for name in names:
            path = os.path.join(folder, name)
            if name.endswith('/'):
                os.makedirs(path)
                with open(os.path.join(path, 'JT.exe'), 'wb') as f:
                    f.write(b'x')
            else:
                with open(path, 'wb') as f:
                    f.write(b'x')
        return folder

    def test_previous_versions_stay_and_everything_else_goes(self):
        folder = self.make('JT-3.0.zip', 'JT-Setup-3.0.exe', 'JT/', 'appunti.txt', 'altro.zip', 'JT-TestDB.exe')
        build.empty_folder(folder, build.KEEP_IN_DIST)
        self.assertEqual(sorted(os.listdir(folder)), ['JT-3.0.zip', 'JT-Setup-3.0.exe'])

    def test_without_keep_it_empties_everything_like_before(self):
        folder = self.make('JT-3.0.zip', 'JT/')
        build.empty_folder(folder)
        self.assertEqual(os.listdir(folder), [])
        self.assertTrue(os.path.isdir(folder))

    def test_a_missing_folder_is_fine(self):
        build.empty_folder(os.path.join(self.tmp, 'non-c-e'), build.KEEP_IN_DIST)

    def test_the_names_the_build_produces_match_what_is_kept(self):
        import fnmatch
        for name in (f'JT-{build.VERSION}.zip', f'JT-Setup-{build.VERSION}.exe', 'JT-3.0.zip', 'JT-10.2.zip'):
            self.assertTrue(any(fnmatch.fnmatch(name, p) for p in build.KEEP_IN_DIST), name)
        for name in ('JT', 'JT-TestDB.exe', 'JT.exe', 'JT-certificato.cer'):
            self.assertFalse(any(fnmatch.fnmatch(name, p) for p in build.KEEP_IN_DIST), name)

    def test_build_cleans_dist_with_the_keep_list(self):
        import inspect
        source = inspect.getsource(build.build_exe)
        self.assertIn('KEEP_IN_DIST', source)
