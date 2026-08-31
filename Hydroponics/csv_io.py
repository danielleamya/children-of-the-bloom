"""
Shared helpers for safely reading/writing the per-device CSVs under `data/`
when `polling.py` (writer) and `dashboard/server.py` (reader) run at the same
time as separate processes.

Two distinct problems can show up when one process writes a CSV while
another reads it, especially on Windows:

1. Torn reads: a naive `df.to_csv(path, ...)` truncates the file before
   writing new content. A reader that opens the file in that window sees an
   empty/partial CSV (parse errors, missing rows) instead of the old or new
   data.
2. Transient `PermissionError` ("used by another process"): antivirus/
   backup/indexing tools (and, occasionally, Windows itself) can briefly
   hold an exclusive-ish handle on a file right after it's written, which
   makes a concurrent open() from another process fail even though nothing
   in *this* code is doing anything wrong. This tends to resolve itself
   within milliseconds.

Mitigations here:
- `atomic_write_csv()` writes to a temp file in the same directory and then
  `os.replace()`s it into place. `os.replace()` is atomic on both Windows
  and POSIX, so a reader only ever sees the fully-old or fully-new file -
  never a truncated one. This fixes problem (1) outright, and shrinks
  problem (2)'s window to just the replace() call itself.
- Both helpers retry with a short backoff on `PermissionError`/`OSError`
  before giving up, to ride out the brief external locks in (2).
"""
import os
import tempfile
import time

import pandas as pd

RETRY_ATTEMPTS = 6
RETRY_BACKOFF_SECONDS = 0.25


def _retry(fn, attempts=RETRY_ATTEMPTS, backoff_seconds=RETRY_BACKOFF_SECONDS):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (PermissionError, OSError) as e:
            last_error = e
            if attempt < attempts:
                time.sleep(backoff_seconds)
    raise last_error


def read_csv_retry(path, **kwargs):
    """pd.read_csv(path, **kwargs), retrying briefly on Windows file-lock errors."""
    return _retry(lambda: pd.read_csv(path, **kwargs))


def atomic_write_csv(df, output_file, **to_csv_kwargs):
    """
    Write `df` to `output_file` atomically: write to a temp file in the same
    directory, then os.replace() it into place, so concurrent readers never
    observe a truncated/partial file. Retries the replace briefly if it hits
    a transient Windows file-lock error.
    """
    to_csv_kwargs.setdefault('index', False)
    directory = os.path.dirname(output_file) or '.'
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f'.{os.path.basename(output_file)}.tmp-', dir=directory,
    )
    try:
        os.close(fd)
        df.to_csv(tmp_path, **to_csv_kwargs)
        _retry(lambda: os.replace(tmp_path, output_file))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
