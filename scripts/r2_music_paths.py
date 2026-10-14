"""Readable, collision-safe keys for imported music, with legacy folder support."""
from pathlib import PurePosixPath
import re

IMPORT_PREFIX = 'music/zip-imports/'


def flat_key(name, digest, occupied):
    filename = PurePosixPath(name.replace('\\', '/')).name
    path = PurePosixPath(filename)
    candidate = IMPORT_PREFIX + filename
    if candidate not in occupied or occupied[candidate] == digest:
        return candidate
    candidate = IMPORT_PREFIX + path.stem + ' [' + digest + ']' + path.suffix
    if candidate in occupied and occupied[candidate] != digest:
        raise ValueError('Conflicting destination audio')
    return candidate


def content_digest(item, head=None):
    relative = item['Key'][len(IMPORT_PREFIX):]
    parts = relative.split('/')
    if len(parts) == 2 and re.fullmatch('[0-9a-f]{64}', parts[0]):
        return parts[0]
    return (head or item).get('Metadata', {}).get('sha256')
