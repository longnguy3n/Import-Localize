"""Read either a user-selected CSV or a comma-separated Unity export snapshot."""
from contextlib import contextmanager
import csv
import io

from .csv_service import CSV_READ_ENCODING, inspect_csv


@contextmanager
def audit_reader(path, data=None):
    if data is None:
        info = inspect_csv(path)
        stream = path.open(encoding=CSV_READ_ENCODING, newline="")
        delimiter = info.delimiter
    else:
        stream = io.StringIO(data.decode("utf-8-sig"), newline="")
        delimiter = ","
    with stream:
        yield csv.reader(stream, delimiter=delimiter, strict=True)
