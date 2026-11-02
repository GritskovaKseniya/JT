"""Log CSV di ogni esecuzione: JT_inserts_log_<data>.csv e JT_errors_log_<data>.csv."""
import csv
import os
from datetime import datetime

from .config import LOG_PREFIX


def write_csv(rows, prefix, directory):
    os.makedirs(directory, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    base = os.path.join(directory, f'{prefix}{timestamp}')
    path, number = base + '.csv', 2
    while os.path.exists(path):                     # stessa data al secondo: si aggiunge un numero
        path, number = f'{base}_{number}.csv', number + 1
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:     # con BOM: Excel riconosce le lettere accentate
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_run_logs(result, directory):
    """Scrive i log solo se ci sono righe. Ritorna i percorsi scritti."""
    paths = []
    if result.successes:
        paths.append(write_csv(result.successes, f'{LOG_PREFIX}_inserts_log_', directory))
    if result.errors:
        paths.append(write_csv(result.errors, f'{LOG_PREFIX}_errors_log_', directory))
    if result.skipped_rows:
        paths.append(write_csv(result.skipped_rows, f'{LOG_PREFIX}_skipped_log_', directory))
    return paths
