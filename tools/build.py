"""Prepara il programma da dare agli altri: una cartella `dist\JTools` con JTools.exe (non serve Python), il file .zip e,
se Inno Setup e' installato, anche il programma di installazione (setup .exe).

    .venv\Scripts\python.exe tools\build.py [--with-azure] [--oracle-client CARTELLA] [--no-installer]

--with-azure         mette nel pacchetto anche la chiave Azure vera (Data\azure_services.json). Senza questa opzione
                     il pacchetto contiene un modello da compilare: la chiave non esce mai per sbaglio.
--no-testdb          non mette nel pacchetto JT-TestDB.exe (lo strumento del database di prova): per chi usa solo JT
--sign               firma JT.exe, JT-TestDB.exe (se c'e') e il setup con un certificato di code signing (vedi sotto)
--oracle-client DIR  copia in `oracle_client` il client Oracle (cartella con oci.dll, a 64 bit) cosi' il programma gira
                     anche su PC senza Oracle installato. Controlla di avere il diritto di ridistribuirlo.

Firma (--sign): il certificato si cerca in questo ordine
  1. file .pfx indicato da JT_SIGN_PFX (password in JT_SIGN_PASSWORD): il certificato dell'azienda;
  2. certificato "JT Jflex Translator" nel Magazzino certificati dell'utente (Cert:\\CurrentUser\\My), per esempio uno
     autofirmato creato con New-SelfSignedCertificate. Un autofirmato non toglie l'avviso di Windows ai colleghi finche'
     non importano JT-certificato.cer (messo nel pacchetto) tra gli editori attendibili.
La marca temporale (JT_SIGN_TIMESTAMP, predefinito DigiCert) tiene valida la firma anche dopo la scadenza del certificato.
"""
import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from jt.config import APP_TITLE, ICON_NAME, VERSION  # noqa: E402

DIST, BUILD = os.path.join(ROOT, 'dist'), os.path.join(ROOT, 'build')
OUT = os.path.join(DIST, 'JTools')
ISCC_PATHS = (r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe', r'C:\Program Files\Inno Setup 6\ISCC.exe',
              os.path.expandvars(r'%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe'))


def step(text):
    print(f'\n== {text}')


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


# Le versioni gia' pronte (JT-3.0.zip, JT-Setup-3.0.exe) restano in dist: costruirne una nuova non le cancella.
KEEP_IN_DIST = ('JT-*.zip', 'JT-Setup-*.exe', 'JTools-*.zip', 'JTools-Setup-*.exe')


def empty_folder(folder, keep=()):
    """Svuota la cartella senza cancellare la cartella stessa: se e' aperta in Esplora file o in un terminale
    Windows non la lascia rimuovere, ma il contenuto si puo' sostituire. I nomi che combaciano con `keep` restano."""
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        if any(fnmatch.fnmatch(name, pattern) for pattern in keep):
            continue
        path = os.path.join(folder, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def check_not_running():
    """Se JT.exe e' aperto Windows non lo lascia sostituire: meglio fermarsi subito che lasciare dist a meta'."""
    for name in ('JTools.exe', 'JT-TestDB.exe'):
        path = os.path.join(OUT, name)
        if os.path.exists(path):
            try:
                open(path, 'r+b').close()           # un exe in esecuzione non si apre in scrittura
            except OSError:
                sys.exit(f"{path} e' in uso: chiudi JT e rilancia la creazione. Non e' stato cancellato nulla.")


def build_exe(with_testdb=True):
    check_not_running()
    step('PyInstaller')
    for folder, keep in ((BUILD, ()), (DIST, KEEP_IN_DIST)):
        empty_folder(folder, keep)
    icon = os.path.join(ROOT, 'Graphics', 'icons', f'{ICON_NAME}.ico')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--noupx', '--windowed', '--name', 'JTools',
        '--icon', icon, '--hidden-import', 'cx_Oracle', '--distpath', DIST, '--workpath', BUILD, '--specpath', BUILD,
        os.path.join(ROOT, 'JT.py'))
    if not with_testdb:
        return
    step('PyInstaller (JT-TestDB: lo strumento del database di prova)')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--noupx', '--console', '--onefile', '--name', 'JT-TestDB',
        '--icon', icon, '--hidden-import', 'cx_Oracle', '--distpath', os.path.join(BUILD, 'testdb'),
        '--workpath', os.path.join(BUILD, 'work2'), '--specpath', BUILD,
        os.path.join(ROOT, 'tools', 'create_test_db.py'))


def copy_files(with_azure, oracle_client, with_testdb=True):
    step("File accanto all'exe (Data, Graphics, LEGGIMI, guida)")
    data = os.path.join(OUT, 'Data')
    os.makedirs(data)
    # Data: solo i file fissi. Mai quelli dell'utente (connessione, ultima scelta) ne' i modelli (.example)
    for name in ('tables.json', 'languages.json', 'glossary.json', 'preferences.json'):
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
    if with_testdb:
        shutil.copy(os.path.join(BUILD, 'testdb', 'JT-TestDB.exe'), OUT)
    shutil.copy(os.path.join(ROOT, 'GUIDA_UTENTE.md'), OUT)
    shutil.copy(os.path.join(ROOT, 'tools', 'LEGGIMI.txt'), OUT)      # breve: cosa serve e come installare
    if oracle_client:
        if not os.path.exists(os.path.join(oracle_client, 'oci.dll')):
            sys.exit(f"--oracle-client: in {oracle_client} non c'e' oci.dll")
        shutil.copytree(oracle_client, os.path.join(OUT, 'oracle_client'))
        print('   client Oracle copiato in oracle_client')
    else:
        print('   client Oracle NON incluso: sul PC deve esserci un client Oracle a 64 bit (vedi GUIDA_UTENTE.md)')


def _powershell(script, **env):
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], cwd=ROOT,
                            capture_output=True, text=True, env={**os.environ, **env})
    if result.returncode:
        sys.exit(f'Firma non riuscita: {result.stdout.strip()} {result.stderr.strip()}')
    return result.stdout.strip()


_FIND_CERT = (
    "$pfx = $env:JT_SIGN_PFX; "
    "if ($pfx) { $cert = Get-PfxCertificate -FilePath $pfx -Password (ConvertTo-SecureString $env:JT_SIGN_PASSWORD -AsPlainText -Force) } "
    "else { $cert = Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert | Where-Object { $_.Subject -like '*JT Jflex Translator*' "
    "-and $_.NotAfter -gt (Get-Date) } | Select-Object -First 1 } "
    "if (-not $cert) { throw 'Nessun certificato di code signing trovato (JT_SIGN_PFX o Cert:\\CurrentUser\\My)' }; ")


def sign(*paths):
    """Firma i file (Authenticode, SHA256, con marca temporale). Si ferma se il certificato manca."""
    timestamp = os.environ.get('JT_SIGN_TIMESTAMP', 'http://timestamp.digicert.com')
    for path in paths:
        out = _powershell(
            _FIND_CERT + "$r = Set-AuthenticodeSignature -FilePath $env:JT_SIGN_FILE -Certificate $cert "
            "-HashAlgorithm SHA256 -TimestampServer $env:JT_SIGN_TS; "
            "if (-not $r.SignerCertificate) { throw $r.StatusMessage }; "
            "'{0}|{1}' -f $r.Status, $r.SignerCertificate.Subject",
            JT_SIGN_FILE=path, JT_SIGN_TS=timestamp)
        print(f'   firmato {os.path.basename(path)}: {out}')


def export_certificate(folder):
    """Il certificato pubblico (senza chiave privata) da dare ai colleghi che vogliono considerarlo attendibile."""
    target = os.path.join(folder, 'JT-certificato.cer')
    _powershell(_FIND_CERT + "Export-Certificate -Cert $cert -FilePath $env:JT_CER_FILE -Type CERT | Out-Null",
                JT_CER_FILE=target)
    print('   certificato pubblico:', target)


def make_zip():
    step('Archivio .zip')
    path = os.path.join(DIST, f'JTools-{VERSION}.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for folder, _, files in os.walk(OUT):
            for name in files:
                full = os.path.join(folder, name)
                z.write(full, os.path.join('JTools', os.path.relpath(full, OUT)))
    print('  ', path)
    return path


def make_installer(with_testdb=True):
    iscc = next((p for p in ISCC_PATHS if os.path.exists(p)), shutil.which('ISCC'))
    if not iscc:
        print("\nInno Setup non installato: niente setup .exe (si puo' dare lo .zip). "
              'Scaricalo da https://jrsoftware.org/isdl.php')
        return None
    step('Programma di installazione (Inno Setup)')
    run(iscc, f'/DAppVersion={VERSION}', f'/DAppName={APP_TITLE}', f'/DSourceDir={OUT}', f'/DOutputDir={DIST}',
        *(['/DWithTestDb=1'] if with_testdb else []), os.path.join(ROOT, 'tools', 'installer.iss'))
    return os.path.join(DIST, f'JTools-Setup-{VERSION}.exe')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--with-azure', action='store_true')
    parser.add_argument('--oracle-client')
    parser.add_argument('--no-installer', action='store_true')
    parser.add_argument('--sign', action='store_true')
    parser.add_argument('--no-testdb', action='store_true')
    args = parser.parse_args()
    with_testdb = not args.no_testdb
    build_exe(with_testdb)
    copy_files(args.with_azure, args.oracle_client, with_testdb)
    if args.sign:
        step('Firma')
        sign(*[os.path.join(OUT, name) for name in ('JTools.exe', 'JT-TestDB.exe') if os.path.exists(os.path.join(OUT, name))])
        export_certificate(OUT)
    results = [make_zip()]
    if not args.no_installer:
        installer = make_installer(with_testdb)
        if installer and args.sign:
            sign(installer)
        results.append(installer)
    print('\nPronto:')
    for path in filter(None, results):
        print('  ', path)
    print('   cartella:', OUT)


if __name__ == '__main__':
    main()
