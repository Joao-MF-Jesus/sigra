"""Lossless CSV row transport. Preserve Python's exact canonical JSON tokens.

Raw numeric tokens (including 0.0/large integers) are strings, never reserialized
as browser Numbers. CSV quoting and CRLF are verified by the row/file SHA-256.
"""
import csv
import io
import json
from app.compact_transport import json_bytes

VERSION="sigra-csv-dictionary-v1"
JSON_COLUMNS={10,11,18,20,29,30}
# The approved 60-result JSON cell is ~7 MB, above csv's 128 KiB
# default. This bounded parser is for server-produced rows, not uploaded CSV.
csv.field_size_limit(32 * 1024 * 1024)


def text_tree(value):
    if isinstance(value,dict):
        return ['o',[[key,text_tree(child)] for key,child in value.items()]]
    if isinstance(value,list):
        return ['a',[text_tree(child) for child in value]]
    return ['s',json_bytes(value).decode('utf-8')]


def tree_text(value):
    kind,content=value
    if kind=='s': return content
    if kind=='a': return '['+','.join(tree_text(child) for child in content)+']'
    if kind=='o': return '{'+','.join(json_bytes(key).decode()+':'+tree_text(child) for key,child in content)+'}'
    raise ValueError('CSV_TREE_INVALID')


def encode_csv_row(text):
    fields=next(csv.reader(io.StringIO(text,newline='')))
    if len(fields)!=36:
        raise ValueError('CSV_COLUMNS_DIFFER')
    cells=[]
    for index,value in enumerate(fields):
        if index in JSON_COLUMNS and value:
            tree=text_tree(json.loads(value))
            if tree_text(tree)!=value:
                raise ValueError('CSV_CANONICAL_JSON_TEXT_DIFFERS')
            cells.append(['j',tree])
        else:
            cells.append(['t',value])
    result={'schema':VERSION,'cells':cells}
    if decode_csv_row(result)!=text:
        raise ValueError('CSV_ROUNDTRIP_DIFFERS')
    return result


def decode_csv_row(value):
    fields=[tree_text(content) if kind=='j' else content for kind,content in value['cells']]
    buffer=io.StringIO(newline='')
    csv.writer(buffer,lineterminator='\r\n').writerow(fields)
    return buffer.getvalue()
