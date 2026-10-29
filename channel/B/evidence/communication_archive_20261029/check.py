"""Verify exact archived public message bytes, with no network or mutations."""
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
assert len(manifest['entries'])==12
assert len({r['file'] for r in manifest['entries']})==12
for row in manifest['entries']:
    data=(root/row['file']).read_bytes()
    assert len(data)==row['bytes']
    assert hashlib.md5(data).hexdigest()==row['md5']
    assert hashlib.sha256(data).hexdigest()==row['sha256']
assert sum(r['kind']=='issue_comment' for r in manifest['entries'])==3
assert sum(r['kind']=='pull_description' for r in manifest['entries'])==8
assert sum(r['kind']=='historical_comment_version' for r in manifest['entries'])==1
print(json.dumps(dict(passed=True,archived_versions=12,current_comments=3,pr_descriptions=8,retained_old_comment_versions=1,scope='Exact text archive only; historical technical claims are quotations, not new acceptance measurements')))
