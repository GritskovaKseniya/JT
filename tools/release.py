"""Procedura di rilascio: dai sorgenti allo .zip da dare ai colleghi, con tutti i controlli.

    .venv\Scripts\python.exe tools\release.py [--version 3.1] [--with-azure] [--installer] [--skip-tests]

Cosa fa, in ordine (si ferma al primo problema, senza lasciare un pacchetto a meta'):
  1. controlla che JT non sia aperto e che il certificato di firma ci sia e non scada a breve;
  2. se si indica --version, aggiorna la versione in jt\\config.py;
  3. lancia tutti i test automatici;
  4. costruisce il pacchetto con le impostazioni di rilascio (firma, senza database di prova, SENZA chiave Azure:
     la chiave abilita la scrittura e si consegna a parte; --with-azure la include, solo per chi la deve avere);
  5. controlla lo .zip: file giusti, nessun dato personale, chiave (assente o vera, come richiesto), exe firmato;
  6. scompatta lo .zip in una cartella temporanea e avvia davvero JTools.exe per qualche secondo.

Non fa commit ne' push: alla fine ricorda cosa controllare.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PACKAGE_FILES = ('JTools/JTools.exe', 'JTools/LEGGIMI.txt', 'JTools/GUIDA_UTENTE.md', 'JTools/JT-certificato.cer', 'JTools/Data/tables.json',
                 'JTools/Data/languages.json', 'JTools/Data/glossary.json', 'JTools/Data/preferences.json', 'JTools/Data/azure_services.json')
FORBIDDEN_FILES = ('JTools/README.md', 'JTools/JT-TestDB.exe')                      # cose che nel pacchetto per i colleghi non vanno
PERSONAL_NAMES = ('connection_data.json', 'query_data.json', 'search_history.json')                # dati personali di chi ha costruito il pacchetto
PLACEHOLDER_KEY = 'INSERISCI-QUI-LA-CHIAVE-AZURE'
CERT_SUBJECT = 'JT Jflex Translator'
WARN_DAYS = 30


def step(text):
    print(f'\n== {text}', flush=True)


def fail(text):
    sys.exit(f'\nSTOP: {text}')


def powershell(script):
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True)
    return result.stdout.strip()


# ------------------------------------------------------------------ controlli (testabili senza Windows)

def check_zip(path, with_azure=True):
    """Elenco dei problemi trovati nello .zip (vuoto = tutto a posto)."""
    problems = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for name in PACKAGE_FILES:
            if name not in names:
                problems.append(f'manca {name}')
        for name in names:
            if name.endswith('/'):
                continue
            base = name.rsplit('/', 1)[-1]
            if name in FORBIDDEN_FILES or base in PERSONAL_NAMES or name.startswith('JTools/Logs/') or name.endswith('.csv'):
                problems.append(f'file che non deve esserci: {name}')
        if not any(n.startswith('JTools/Graphics/icons/') and n.endswith('.ico') for n in names):
            problems.append("manca l'icona (Graphics/icons)")
        if 'JTools/Data/azure_services.json' in names:
            text = z.read('JTools/Data/azure_services.json').decode('utf-8', 'replace')
            has_placeholder = PLACEHOLDER_KEY in text
            if with_azure and has_placeholder:
                problems.append('la chiave Azure e\' ancora il segnaposto')
            if not with_azure and not has_placeholder:
                problems.append("la chiave Azure e' dentro il pacchetto ma non doveva esserci")
    return problems


def bump_version(config_path, version):
    """Scrive la nuova versione in config.py. Ritorna la vecchia."""
    with open(config_path, encoding='utf-8', newline='') as f:
        text = f.read()
    match = re.search(r"^VERSION = '([^']*)'", text, re.M)
    if not match:
        raise ValueError('VERSION non trovata in config.py')
    new = text[:match.start(1)] + version + text[match.end(1):]
    with open(config_path, 'w', encoding='utf-8', newline='') as f:
        f.write(new)
    return match.group(1)


# ------------------------------------------------------------------ passi

def check_environment():
    step('Controlli iniziali')
    if 'JTools.exe' in subprocess.run(['tasklist'], capture_output=True, text=True).stdout:
        fail('JTools.exe e\' aperto: chiudilo e rilancia.')
    out = powershell(
        "$c = Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert | Where-Object { $_.Subject -like '*" + CERT_SUBJECT + "*' "
        "-and $_.NotAfter -gt (Get-Date) } | Sort-Object NotAfter -Descending | Select-Object -First 1; "
        "if ($c) { [int]($c.NotAfter - (Get-Date)).TotalDays } else { 'none' }")
    if os.environ.get('JT_SIGN_PFX'):
        print('   certificato: file indicato da JT_SIGN_PFX')
    elif out == 'none' or not out:
        fail(f"nessun certificato di firma valido ('{CERT_SUBJECT}' in Cert:\\CurrentUser\\My). Vedi RILASCIO.md, sezione Certificato.")
    elif int(out) < WARN_DAYS:
        print(f'   ATTENZIONE: il certificato scade tra {out} giorni (vedi RILASCIO.md)')
    else:
        print(f'   certificato di firma valido ancora {out} giorni')


def run_tests():
    step('Test automatici')
    result = subprocess.run([sys.executable, '-W', 'error::ResourceWarning', '-m', 'unittest', 'discover', '-s', 'tests'],
                            cwd=ROOT, capture_output=True, text=True)
    tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
    print('   ' + '\n   '.join(tail))
    if result.returncode:
        fail('i test non passano: non si costruisce nessun pacchetto.')


def build(with_azure, installer):
    step('Costruzione del pacchetto')
    command = [sys.executable, os.path.join('tools', 'build.py'), '--sign', '--no-testdb']
    if with_azure:
        command.append('--with-azure')
    if not installer:
        command.append('--no-installer')
    if subprocess.run(command, cwd=ROOT).returncode:
        fail('la costruzione del pacchetto non e\' riuscita (vedi i messaggi sopra).')


def verify(zip_path, with_azure):
    step('Controllo dello .zip')
    problems = check_zip(zip_path, with_azure)
    out = powershell("$s = Get-AuthenticodeSignature '" + os.path.join(ROOT, 'dist', 'JTools', 'JTools.exe') + "'; "
                     "if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { 'NONE' }")
    if CERT_SUBJECT not in out:
        problems.append(f'JTools.exe non e\' firmato (firma trovata: {out or "nessuna"})')
    for problem in problems:
        print('   PROBLEMA:', problem)
    if problems:
        fail('lo .zip non e\' a posto: non darlo ai colleghi.')
    print(f'   ok: {os.path.getsize(zip_path) // 1024 // 1024} MB, file giusti, nessun dato personale, exe firmato')


def smoke_test(zip_path):
    step('Prova: scompatto lo .zip e avvio JTools.exe')
    with tempfile.TemporaryDirectory() as folder:
        extracted, local = os.path.join(folder, 'zip'), os.path.join(folder, 'local')
        os.makedirs(local)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extracted)
        process = subprocess.Popen([os.path.join(extracted, 'JTools', 'JTools.exe')], env={**os.environ, 'LOCALAPPDATA': local})
        try:
            time.sleep(6)
            if process.poll() is not None:
                fail(f'JTools.exe si e\' chiuso da solo (codice {process.returncode}).')
            seeded = os.path.exists(os.path.join(local, 'JT', 'azure_services.json'))
        finally:
            process.kill()
            process.wait()
        if not seeded:
            fail('JTools.exe parte ma non crea azure_services.json nella cartella dell\'utente.')
    print('   ok: JTools.exe parte da solo dalla copia scompattata e prepara la cartella dell\'utente')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', help="nuova versione (per esempio 3.1): si scrive in jt\\config.py")
    parser.add_argument('--with-azure', action='store_true', help="include la chiave Azure vera (di solito NO: si consegna a parte)")
    parser.add_argument('--no-azure', action='store_true', help=argparse.SUPPRESS)      # vecchio nome: ora e' la regola
    parser.add_argument('--installer', action='store_true', help="crea anche il setup (serve Inno Setup)")
    parser.add_argument('--skip-tests', action='store_true', help='salta i test (sconsigliato)')
    args = parser.parse_args()

    check_environment()
    if args.version:
        step(f'Versione {args.version}')
        print('   prima:', bump_version(os.path.join(ROOT, 'jt', 'config.py'), args.version))
    if not args.skip_tests:
        run_tests()
    with_azure = args.with_azure and not args.no_azure
    build(with_azure, args.installer)
    from jt.config import VERSION      # letta dopo l'eventuale cambio
    zip_path = os.path.join(ROOT, 'dist', f'JTools-{VERSION}.zip')
    verify(zip_path, with_azure)
    smoke_test(zip_path)
    print(f'\nPRONTO: {zip_path}')
    print('Ora: guarda `git status`, fai commit e push del lavoro e manda lo .zip ai colleghi (vedi RILASCIO.md).')


if __name__ == '__main__':
    main()
