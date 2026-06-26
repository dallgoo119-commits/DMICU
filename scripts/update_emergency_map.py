import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_HTML = ROOT / "gwangju_emergency_map.html"

REGIONS = {
    "광주": "15",
    "전남": "26",
}

GRADE_BY_CODE = {
    "A1500001": "B",
    "A1500002": "B",
    "A1500003": "A",
    "A1500004": "B",
    "A1500005": "B",
    "A1500006": "A",
    "A1500007": "B",
    "A1500008": "B",
    "A1500009": "B",
    "A1500010": "B",
    "A1500011": "B",
    "A1500012": "A",
    "A1500013": "B",
    "A1500014": "B",
    "A1500015": "A",
    "A1500016": "B",
    "A1500017": "C",
    "A1500018": "C",
    "A1500019": "B",
    "A1500020": "B",
    "A1500021": "B",
    "A1500022": "B",
    "A1502007": "B",
    "A2600001": "B",
    "A2600003": "A",
    "A2600004": "-",
    "A2600005": "C",
    "A2600006": "C",
    "A2600007": "B",
    "A2600008": "B",
    "A2600009": "B",
    "A2600010": "C",
    "A2600011": "B",
    "A2600014": "B",
    "A2600015": "B",
    "A2600016": "A",
    "A2600017": "B",
    "A2600018": "B",
    "A2600019": "B",
    "A2600020": "C",
    "A2600021": "B",
    "A2600022": "A",
    "A2600024": "C",
    "A2600027": "A",
    "A2600029": "C",
    "A2600032": "B",
    "A2600034": "B",
    "A2600035": "C",
    "A2600037": "C",
    "A2600040": "B",
    "A2600050": "C",
    "A2600051": "A",
    "A2600052": "C",
    "A2600054": "C",
    "A2600056": "A",
    "A2600061": "C",
    "A2600066": "C",
    "A2600068": "B",
    "A2600070": "B",
    "A2600077": "A",
    "A2602088": "-",
    "A2602211": "B",
}


def request_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://mediboard.nemc.or.kr/emergency_room_in_hand",
            "User-Agent": "DMICU-bed-map-updater/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def extract_array(source, name):
    prefix = f"const {name}="
    start = source.index(prefix) + len(prefix)
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return json.loads(source[start : index + 1])
    raise ValueError(f"Could not extract {name}")


def replace_array(source, name, value):
    prefix = f"const {name}="
    start = source.index(prefix) + len(prefix)
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                return source[:start] + encoded + source[index + 1 :]
    raise ValueError(f"Could not replace {name}")


def get_items(obj):
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        return []
    for key in ("result", "data", "list", "items", "content"):
        value = obj.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = get_items(value)
            if nested:
                return nested
    return []


def pick(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def number(value):
    if value in (None, "", "-"):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def percent(available, total):
    if total and available is not None:
        return round((total - available) / total * 100, 1)
    return None


def class_code(type_name):
    text = type_name or ""
    if "외상" in text:
        return "trauma"
    if "권역응급" in text:
        return "regional"
    if "지역응급의료센터" in text:
        return "local_center"
    if "지역응급의료기관" in text:
        return "local"
    return "unknown"


def collect_messages(row):
    messages = []
    groups = (
        ("erMessages", "응급실"),
        ("unavailableMessages", "수용제한"),
        ("adMessages", "공지"),
    )
    for key, label in groups:
        for item in row.get(key) or []:
            messages.append(
                {
                    "group": label,
                    "category": item.get("category") or "",
                    "reason": item.get("reason") or "",
                    "detail": item.get("detail") or "",
                    "message": item.get("message") or "",
                }
            )
    return messages


def fetch_rows(previous_by_code):
    rows = []
    for region, region_code in REGIONS.items():
        url = (
            "https://mediboard.nemc.or.kr/api/v1/search/handy"
            f"?searchCondition=regional&emogloca={region_code}"
        )
        for item in get_items(request_json(url)):
            code = pick(item, "emogCode", "hpid", "dutyId")
            if not code:
                continue
            previous = previous_by_code.get(code, {})
            general_available = number(pick(item, "generalEmergencyAvailable"))
            general_total = number(pick(item, "generalEmergencyTotal"))
            child_available = number(pick(item, "childEmergencyAvailable"))
            child_total = number(pick(item, "childEmergencyTotal"))
            type_name = (
                pick(item, "emergencyInstitutionType", "emogTypeName", "dutyEmclsName")
                or previous.get("type")
                or "미분류"
            )
            row = {
                "region": region,
                "code": code,
                "name": pick(item, "emergencyRoomName", "dutyName", "hospitalName")
                or previous.get("name")
                or "",
                "type": type_name,
                "grade": GRADE_BY_CODE.get(code, previous.get("grade", "-")),
                "lat": float(pick(item, "latitude", "lat", "wgs84Lat") or previous["lat"]),
                "lon": float(
                    pick(item, "longitude", "lon", "lng", "wgs84Lon") or previous["lon"]
                ),
                "general_available": general_available,
                "general_total": general_total,
                "general_saturation": percent(general_available, general_total),
                "child_available": child_available,
                "child_total": child_total,
                "child_saturation": percent(child_available, child_total),
                "message_count": len(collect_messages(item)),
                "address": pick(item, "address", "dutyAddr", "addr")
                or previous.get("address")
                or "",
                "messages": collect_messages(item),
                "classCode": class_code(type_name),
            }
            rows.append(row)

    order = {"trauma": 0, "regional": 1, "local_center": 2, "local": 3, "unknown": 4}
    return sorted(rows, key=lambda r: (r["region"], order[r["classCode"]], r["name"]))


def update_history(history, rows, captured_at):
    today = captured_at[:10]
    by_key = {(row["date"], row["code"]): row for row in history}
    for row in rows:
        by_key[(today, row["code"])] = {
            "date": today,
            "region": row["region"],
            "code": row["code"],
            "name": row["name"],
            "type": row["type"],
            "grade": row["grade"],
            "general_available": row["general_available"],
            "general_total": row["general_total"],
            "general_saturation": row["general_saturation"],
            "child_available": row["child_available"],
            "child_total": row["child_total"],
            "child_saturation": row["child_saturation"],
            "updated_at": captured_at,
        }
    return [by_key[key] for key in sorted(by_key)]


def summary(rows):
    def known(kind):
        return [row for row in rows if row[f"{kind}_available"] is not None and row[f"{kind}_total"]]

    general = known("general")
    child = known("child")
    general_available = sum(row["general_available"] for row in general)
    general_total = sum(row["general_total"] for row in general)
    child_available = sum(row["child_available"] for row in child)
    child_total = sum(row["child_total"] for row in child)
    return {
        "total": len(rows),
        "gwangju": sum(1 for row in rows if row["region"] == "광주"),
        "jeonnam": sum(1 for row in rows if row["region"] == "전남"),
        "general_available": general_available,
        "general_total": general_total,
        "general_saturation": percent(general_available, general_total),
        "child_available": child_available,
        "child_total": child_total,
        "child_saturation": percent(child_available, child_total),
        "grades": {
            grade: sum(1 for row in rows if row["grade"] == grade)
            for grade in ("A", "B", "C", "-")
        },
    }


def update_static_text(source, captured_at, stats):
    source = re.sub(
        r"지도 생성 [0-9T:\-+.Z]+",
        f"지도 생성 {captured_at}",
        source,
        count=1,
    )
    source = source.replace(
        "저장된 일자별 포화도 그래프를 확인할 수 있습니다.",
        "2시간마다 갱신되는 최신 병상 현황과 저장된 일자별 포화도 그래프를 확인할 수 있습니다.",
        1,
    )
    source = re.sub(
        r'<div class="card"><strong>\d+</strong><span>응급의료기관 등<br>광주 \d+ / 전남 \d+</span></div>',
        f'<div class="card"><strong>{stats["total"]}</strong><span>응급의료기관 등<br>광주 {stats["gwangju"]} / 전남 {stats["jeonnam"]}</span></div>',
        source,
        count=1,
    )
    source = re.sub(
        r'<div class="card"><strong>남은 [^<]+ / 전체 [^<]+</strong><span>일반 응급실 남은 병상/전체 병상<br>실시간 포화 [^<]+%</span></div>',
        f'<div class="card"><strong>남은 {stats["general_available"]} / 전체 {stats["general_total"]}</strong><span>일반 응급실 남은 병상/전체 병상<br>실시간 포화 {stats["general_saturation"]}%</span></div>',
        source,
        count=1,
    )
    source = re.sub(
        r'<div class="card"><strong>남은 [^<]+ / 전체 [^<]+</strong><span>소아 응급실 남은 병상/전체 병상<br>실시간 포화 [^<]+%</span></div>',
        f'<div class="card"><strong>남은 {stats["child_available"]} / 전체 {stats["child_total"]}</strong><span>소아 응급실 남은 병상/전체 병상<br>실시간 포화 {stats["child_saturation"]}%</span></div>',
        source,
        count=1,
    )
    source = re.sub(
        r'<div class="card"><strong>A \d+ / B \d+ / C \d+</strong><span>2024 평가등급<br>미분류 \d+</span></div>',
        f'<div class="card"><strong>A {stats["grades"]["A"]} / B {stats["grades"]["B"]} / C {stats["grades"]["C"]}</strong><span>2024 평가등급<br>미분류 {stats["grades"]["-"]}</span></div>',
        source,
        count=1,
    )
    source = source.replace(
        "일자별 그래프는 저장된 daily_er_bed_saturation.csv를 기준으로 하며, 미수집 날짜는 비워 둡니다.",
        "일자별 그래프는 자동 저장된 병상 스냅샷을 기준으로 하며, 미수집 날짜는 비워 둡니다.",
        1,
    )
    return source


def main():
    source = MAP_HTML.read_text(encoding="utf-8")
    previous_data = extract_array(source, "DATA")
    history = extract_array(source, "HISTORY")
    previous_by_code = {row["code"]: row for row in previous_data}
    rows = fetch_rows(previous_by_code)
    captured_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    history = update_history(history, rows, captured_at)
    stats = summary(rows)
    source = replace_array(source, "DATA", rows)
    source = replace_array(source, "HISTORY", history)
    source = update_static_text(source, captured_at, stats)
    MAP_HTML.write_text(source, encoding="utf-8", newline="\n")
    print(
        "updated "
        f"{MAP_HTML.name}: rows={stats['total']} "
        f"general={stats['general_available']}/{stats['general_total']} "
        f"child={stats['child_available']}/{stats['child_total']} "
        f"captured_at={captured_at}"
    )


if __name__ == "__main__":
    main()
