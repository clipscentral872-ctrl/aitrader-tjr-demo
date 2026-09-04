"""Read a multipart/form-data upload.

Python 3.13 removed the `cgi` module, which is where this used to come from,
and `email` will happily eat a hundred megabytes of CSV into memory as text
and mangle the line endings on the way. So this reads the parts directly.

It handles exactly what a browser sends when it posts a FormData of files:
a boundary, a few headers per part, then the bytes. Nothing more, because
nothing more is posted here.
"""
import re

# A filename can be quoted, and can contain escaped quotes. RFC 5987's
# filename* form is not produced by any current browser for a plain upload,
# so the quoted form is the only one that needs reading.
FILENAME = re.compile(rb'filename="((?:[^"\\]|\\.)*)"')
NAME = re.compile(rb'\bname="((?:[^"\\]|\\.)*)"')

MAX_BYTES = 64 * 1024 * 1024      # a session's exports are a few hundred KB


def _boundary(content_type):
    for bit in content_type.split(";"):
        bit = bit.strip()
        if bit.lower().startswith("boundary="):
            b = bit[9:].strip().strip('"')
            if not b:
                break
            return b.encode("latin-1")
    raise ValueError("no boundary in Content-Type")


def parse_multipart(stream, content_type, length):
    """Yield (filename, bytes) for every file part in the body.

    Parts with no filename are form fields rather than files and are skipped,
    which is what the diary wants: it only ever sends files.
    """
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("not a multipart upload")
    if length <= 0:
        raise ValueError("empty upload")
    if length > MAX_BYTES:
        raise ValueError("upload too large")

    sep = b"--" + _boundary(content_type)
    body = stream.read(length)

    out = []
    for chunk in body.split(sep):
        if chunk in (b"", b"--", b"--\r\n", b"\r\n"):
            continue
        # headers, blank line, then the content, then the trailing CRLF that
        # belongs to the boundary rather than the file
        head, _, data = chunk.partition(b"\r\n\r\n")
        if not _:
            continue
        m = FILENAME.search(head)
        if not m:
            continue
        name = m.group(1).replace(b'\\"', b'"').decode("utf-8", "replace")
        if not name:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        out.append((name, data))
    if not out:
        raise ValueError("no files in the upload")
    return out
