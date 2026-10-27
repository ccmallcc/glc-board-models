"""Read-only check of the published B receipt vectors, stdlib only."""
import hashlib
import json
from pathlib import Path
import struct

d=Path(__file__).resolve().parent
peer=d.parents[1]/'A/evidence/hybrid_IMG0036_316B.glc'
for name,size,md5 in [
    ('s175_rx1.glc',292,'e9b07f13c65186fb461b377b5f024d28'),
    ('s177_rx1.glc',316,'21654a58efefcecbfdf33a0ad926d53c'),
    ('s177_rx1.png',119576,'6b43bc80ea2f244323a51455e2043b4f')]:
    data=(d/name).read_bytes()
    assert len(data)==size and hashlib.md5(data).hexdigest()==md5,name
assert (d/'s175_rx1.glc').read_bytes()==(d/'s085_container_e9b07f13.glc').read_bytes()
assert (d/'s177_rx1.glc').read_bytes()==peer.read_bytes()
assert list(struct.unpack_from('>4sBBH17I',(d/'s177_rx1.glc').read_bytes())[15:20])==[28,64,56,48,44]
print(json.dumps({'passed':True,'s175_equals_legacy':True,'s177_equals_peer':True}))
