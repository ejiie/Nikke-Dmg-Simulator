"""global-metadata.dat (il2cpp v31) → 표 Record 클래스의 필드명·순서 추출.

StaticData `.mpk` 표를 디코드하려면 각 행(Record) 의 필드 순서가 필요한데, 그건 게임의
il2cpp 타입 정의(global-metadata.dat)에 있다. 이 파서가 그걸 뽑는다. (바이너리 registration
불필요 — 메타데이터만으로 타입·필드 이름/순서 확보. 타입 int/float/int64 는 디코드 시 이름+데이터로 추론.)

사용: python metadata_fields.py <global-metadata.dat> [out.json]
  → 모든 `*Record`(표 행 스키마)를 {클래스명: [필드…]} 로 JSON 출력.

헤더 오프셋(v24~31 안정): string=idx6, fields=idx24, typeDefs=idx40.
구조체 크기(v31): TypeDefinition=88B(nameIndex@0, fieldStart@32, field_count(u16)@68), Field=12B(nameIndex@0).
검증: AttractiveLevelRecord = 21필드(Id/Attractive_level/Attractive_point/…_rate) 나오면 오프셋 정확.
"""
import json
import re
import struct
import sys


def extract(metadata_path):
    data = open(metadata_path, "rb").read()
    sanity, version = struct.unpack_from("<Ii", data, 0)
    if sanity != 0xFAB11BAF:
        raise SystemExit(f"❌ 매직 불일치 {sanity:08x} — global-metadata.dat 아님(복호 필요?)")

    def hdr(i):
        return struct.unpack_from("<i", data, i * 4)[0]

    str_off = hdr(6)
    fld_off = hdr(24)
    td_off, td_size = hdr(40), hdr(41)
    TD, FD = 88, 12

    def cstr(idx):
        end = data.index(b"\x00", str_off + idx)
        return data[str_off + idx:end].decode("utf-8", "replace")

    def field_name(j):
        return cstr(struct.unpack_from("<i", data, fld_off + j * FD)[0])

    def clean(n):
        m = re.match(r"<(.+)>k__BackingField", n)
        return m.group(1) if m else n

    records = {}
    for i in range(td_size // TD):
        base = td_off + i * TD
        name = cstr(struct.unpack_from("<i", data, base)[0])
        if name.endswith("Record") and not name.endswith("RecordFormatter"):
            fs = struct.unpack_from("<i", data, base + 32)[0]
            fc = struct.unpack_from("<H", data, base + 68)[0]
            if fs >= 0 and fc > 0:
                records[name] = [clean(field_name(fs + k)) for k in range(fc)]
    return version, records


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("사용: python metadata_fields.py <global-metadata.dat> [out.json]")
    ver, recs = extract(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "all_records.json"
    json.dump(recs, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"il2cpp metadata v{ver} — {len(recs)} Record 클래스 → '{out}'")
    ok = recs.get("AttractiveLevelRecord", [])
    print(f"검증 AttractiveLevelRecord: {len(ok)}필드 {'✅' if len(ok)==21 else '⚠️ 오프셋 확인'}")
