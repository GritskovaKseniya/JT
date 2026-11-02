"""Prepara il programma da dare agli altri: una cartella `dist\JT` con JT.exe (non serve Python), il file .zip e,
se Inno Setup e' installato, anche il programma di installazione (setup .exe).

    .venv\Scripts\python.exe tools\build.py [--with-azure] [--oracle-client CARTELLA] [--no-installer]

--with-azure         mette nel pacchetto anche la chiave Azure vera (Data\azure_services.json). Senza questa opzione
                     il pacchetto contiene un modello da compilare: la chiave non esce mai per sbaglio.
--oracle-client DIR  copia in `oracle_client` il client Oracle (cartella con oci.dll, a 64 bit) cosi' il programma gira
                     anche su PC senza Oracle installato. Controlla di avere il diritto di ridistribuirlo.
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from jt.config import APP_TITLE, ICON_NAME, VERSION  # noqa: E402

DIST, BUILD = os.path.join(ROOT, 'dist'), os.path.join(ROOT, 'build')
OUT = os.path.join(DIST, 'JT')
ISCC_PATHS = (r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe', r'C:\Program Files\Inno Setup 6\ISCC.exe',
              os.path.expandvars(r'%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe'))


def step(text):
    print(f'\n== {text}')


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def check_not_running():
    """Se JT.exe e' aperto Windows non lo lascia sostituire: meglio fermarsi subito che lasciare dist a meta'."""
    for name in ('JT.exe', 'JT-TestDB.exe'):
        path = os.path.join(OUT, name)
        if os.path.exists(path):
            try:
                open(path, 'r+b').close()           # un exe in esecuzione non si apre in scrittura
            except OSError:
                sys.exit(f"{path} e' in uso: chiudi JT e rilancia la creazione. Non e' stato cancellato nulla.")


def build_exe():
    check_not_running()
    step('PyInstaller')
    for folder in (BUILD, DIST):
        if os.path.exists(folder):
            shutil.rmtree(folder)
    icon = os.path.join(ROOT, 'Graphics', 'icons', f'{ICON_NAME}.ico')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--noupx', '--windowed', '--name', 'JT',
        '--icon', icon, '--hidden-import', 'cx_Oracle', '--distpath', DIST, '--workpath', BUILD, '--specpath', BUILD,
        os.path.join(ROOT, 'JT.py'))
    step('PyInstaller (JT-TestDB: lo strumento del database di prova)')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--noupx', '--console', '--onefile', '--name', 'JT-TestDB',
        '--icon', icon, '--hidden-import', 'cx_Oracle', '--distpath', os.path.join(BUILD, 'testdb'),
        '--workpath', os.path.join(BUILD, 'work2'), '--specpath', BUILD,
        os.path.join(ROOT, 'tools', 'create_test_db.py'))


def copy_files(with_azure, oracle_client):
    step("File accanto all'exe (Data, Graphics, guide)")
    data = os.path.join(OUT, 'Data')
    os.makedirs(data)
    # Data: solo i file fissi. Mai quelli dell'utente (connessione, ultima scelta) ne' i modelli (.example)
    for name in ('tables.json', 'languages.json', 'glossary.json'):
        shutil.copy(os.path.join(ROOT, 'Data', name), data)
    source = 'azure_services.json' if with_azure else 'azure_services.example.json'
    shutil.copy(os.path.join(ROOT, 'Data', source), os.path.join(data, 'azure_services.json'))
    if not with_azure:
        print("   chiave Azure NON inclusa: Data\\azure_services.json e' un modello da compilare")
    # solo le immagini che servono: l'icona scelta e i pallini dei passi
    graphics = os.path.join(OUT, 'Graphics')
    os.makedirs(os.path.join(graphics, 'icons'))
    shutil.copy(os.path.join(ROOT, 'Graphics', 'icons', f'{ICON_NAME}.ico'), os.path.join(graphics, 'icons'))
    for name in os.listdir(os.path.join(ROOT, 'Graphics')):
        if name.endswith('.png'):
            shutil.copy(os.path.join(ROOT, 'Graphics', name), graphics)
    shutil.copy(os.path.join(BUILD, 'testdb', 'JT-TestDB.exe'), OUT)
    for name in ('GUIDA_UTENTE.md', 'README.md'):
        if os.path.exists(os.path.join(ROOT, name)):
            shutil.copy(os.path.join(ROOT, name), OUT)
    if oracle_client:
        if not os.path.exists(os.path.join(oracle_client, 'oci.dll')):
            sys.exit(f"--oracle-client: in {oracle_client} non c'e' oci.dll")
        shutil.copytree(oracle_client, os.path.join(OUT, 'oracle_client'))
        print('   client Oracle copiato in oracle_client')
    else:
        print('   client Oracle NON incluso: sul PC deve esserci un client Oracle a 64 bit (vedi GUIDA_UTENTE.md)')


def make_zip():
    step('Archivio .zip')
    path = os.path.join(DIST, f'JT-{VERSION}.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for folder, _, files in os.walk(OUT):
            for name in files:
                full = os.path.join(folder, name)
                z.write(full, os.path.join('JT', os.path.relpath(full, OUT)))
    print('  ', path)
    return path


def make_installer():
    iscc = next((p for p in ISCC_PATHS if os.path.exists(p)), shutil.which('ISCC'))
    if not iscc:
        print("\nInno Setup non installato: niente setup .exe (si puo' dare lo .zip). "
              'Scaricalo da https://jrsoftware.org/isdl.php')
        return None
    step('Programma di installazione (Inno Setup)')
    run(iscc, f'/DAppVersion={VERSION}', f'/DAppName={APP_TITLE}', f'/DSourceDir={OUT}', f'/DOutputDir={DIST}',
        os.path.join(ROOT, 'tools', 'installer.iss'))
    return os.path.join(DIST, f'JT-Setup-{VERSION}.exe')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--with-azure', action='store_true')
    parser.add_argument('--oracle-client')
    parser.add_argument('--no-installer', action='store_true')
    args = parser.parse_args()
    build_exe()
    copy_files(args.with_azure, args.oracle_client)
    results = [make_zip()]
    if not args.no_installer:
        results.append(make_installer())
    print('\nPronto:')
    for path in filter(None, results):
        print('  ', path)
    print('   cartella:', OUT)


if __name__ == '__main__':
    main()
