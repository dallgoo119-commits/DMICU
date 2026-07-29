import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_HTML = ROOT / "gwangju_emergency_map.html"
INDEX_HTML = ROOT / "index.html"
NATIONAL_RESEARCH_DIR = ROOT / "data" / "national_daily"
NATIONAL_SNAPSHOT_DIR = ROOT / "data" / "national_snapshots"
KST = timezone(timedelta(hours=9))
HISTORY_SCHEMA_VERSION = 2
HISTORY_DATE_BASIS = "Asia/Seoul"
HISTORY_AGGREGATION = "successful_snapshot_mean"


def parse_timestamp(value):
    """Parse an ISO timestamp and normalize naive values as Korea time."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def kst_date(value):
    """Return the Korean calendar date for an arbitrary ISO timestamp."""
    return parse_timestamp(value).astimezone(KST).date().isoformat()


def capture_timestamp():
    """Collector observation time. This is not the upstream source update time."""
    return datetime.now(KST).isoformat(timespec="seconds")

# 2026-07-01 전남광주통합특별시 출범으로 NEMC handy API가 개편됨.
# - 구 파라미터 emogloca(광주 15 / 전남 26) 폐지 -> HTTP 400
# - 신 파라미터 bjdcd1 사용, 전남광주통합특별시 신규 시도코드 = 12
# 기관 코드(emogCode) 체계는 유지되므로 A15* -> 구 광주, A26* -> 구 전남으로 권역을 구분한다.
REGION_BY_PREFIX = {
    "A15": "광주",
    "A26": "전남",
}


def region_of(code, previous):
    text = str(code)
    for prefix, name in REGION_BY_PREFIX.items():
        if text.startswith(prefix):
            return name
    return previous.get("region") or "기타"


# 전국 응급실 포화 패널용: 2026-07 개편 기준 시도별 bjdcd1 코드
NATIONAL_CODES = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기",
    "43": "충북", "44": "충남", "47": "경북", "48": "경남",
    "50": "제주", "51": "강원", "52": "전북", "12": "광주전남",
}
NATIONAL_THRESHOLD = 80  # 일반 응급실 병상 포화도(%) 컷


def fetch_all_regions():
    """전 시도를 한 번씩만 조회한다. 지역 지도와 전국 패널이 결과를 공유한다."""
    items_by_code = {}
    failed_labels = []
    for code, label in NATIONAL_CODES.items():
        url = (
            "https://mediboard.nemc.or.kr/api/v1/search/handy"
            f"?searchCondition=regional&bjdcd1={code}"
        )
        try:
            items = get_items(request_json(url))
            if not items:
                failed_labels.append(label)
            else:
                items_by_code[code] = items
        except Exception:
            failed_labels.append(label)
        time.sleep(0.2)
    return items_by_code, failed_labels


def fetch_national(items_by_code, failed_labels):
    """수집된 전 시도 데이터에서 전체 기관 흐름과 포화도 컷 이상 패널을 만든다."""
    unique_rows = {}
    raw_item_count = 0
    invalid_count = 0
    duplicate_count = 0
    conflicting_codes = set()
    for code, items in items_by_code.items():
        label = NATIONAL_CODES[code]
        for item in items:
            raw_item_count += 1
            available = number(pick(item, "generalEmergencyAvailable"))
            beds_total = number(pick(item, "generalEmergencyTotal"))
            if not beds_total or available is None:
                invalid_count += 1
                continue
            saturation = percent(available, beds_total)
            if saturation is None:
                invalid_count += 1
                continue
            emog = str(pick(item, "emogCode", "hpid", "dutyId") or "")
            if emog.startswith("A15"):
                region = "광주"
            elif emog.startswith("A26"):
                region = "전남"
            else:
                region = label
            lat = pick(item, "latitude", "lat", "wgs84Lat")
            lon = pick(item, "longitude", "lon", "lng", "wgs84Lon")
            row = {
                "c": emog or f"{region}|{pick(item, 'emergencyRoomName', 'dutyName', 'hospitalName') or ''}",
                "r": region,
                "n": pick(item, "emergencyRoomName", "dutyName", "hospitalName") or "",
                "t": pick(
                    item, "emergencyInstitutionType", "emogTypeName", "dutyEmclsName"
                )
                or "",
                "a": available,
                "o": beds_total,
                "s": saturation,
                "m": len(collect_messages(item)),
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
                "addr": pick(item, "address", "dutyAddr", "addr") or "",
            }
            key = emog or f'{region}|{row["n"]}'
            previous = unique_rows.get(key)
            if previous is not None:
                duplicate_count += 1
                material_fields = ("r", "n", "t", "a", "o", "s", "m", "lat", "lon", "addr")
                if any(previous.get(field) != row.get(field) for field in material_fields):
                    conflicting_codes.add(key)
                # Keep the more complete record. Ties keep the first region response
                # so one API call cannot count the same institution twice.
                score = sum(row.get(field) not in (None, "") for field in material_fields)
                previous_score = sum(
                    previous.get(field) not in (None, "") for field in material_fields
                )
                if score > previous_score:
                    unique_rows[key] = row
            else:
                unique_rows[key] = row

    history_rows = list(unique_rows.values())
    rows = [row for row in history_rows if row["s"] >= NATIONAL_THRESHOLD]
    rows.sort(key=lambda x: (-x["s"], x["r"], x["n"]))
    quality = {
        "raw_item_count": raw_item_count,
        "unique_institution_count": len(history_rows),
        "duplicate_count": duplicate_count,
        "conflicting_duplicate_count": len(conflicting_codes),
        "invalid_count": invalid_count,
    }
    return (
        rows,
        len(history_rows),
        failed_labels,
        len(items_by_code),
        history_rows,
        quality,
    )

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


def request_json(url, retries=2):
    last_error = None
    for attempt in range(retries + 1):
        try:
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
        except Exception as error:  # noqa: BLE001 - 일시 장애는 재시도로 흡수
            last_error = error
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last_error


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


def fetch_rows(previous_by_code, items):
    if not items:
        # 광주·전남 데이터가 없으면 기존 지도를 지우지 않도록 실패 처리한다
        raise RuntimeError("전남광주(bjdcd1=12) 수집 실패; 지도 갱신을 중단합니다")
    rows = []
    for item in items:
        code = pick(item, "emogCode", "hpid", "dutyId")
        if not code:
            continue
        previous = previous_by_code.get(code, {})
        lat = pick(item, "latitude", "lat", "wgs84Lat") or previous.get("lat")
        lon = pick(item, "longitude", "lon", "lng", "wgs84Lon") or previous.get("lon")
        if lat is None or lon is None:
            # 좌표가 없는 신규 기관은 지도에 표기할 수 없으므로 건너뛴다
            continue
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
            "region": region_of(code, previous),
            "code": code,
            "name": pick(item, "emergencyRoomName", "dutyName", "hospitalName")
            or previous.get("name")
            or "",
            "type": type_name,
            "grade": GRADE_BY_CODE.get(code, previous.get("grade", "-")),
            "lat": float(lat),
            "lon": float(lon),
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

    if not rows:
        # API가 빈 결과를 주면 기존 지도 데이터를 지우지 않도록 실패 처리한다
        raise RuntimeError("NEMC handy API returned no rows; aborting update")

    order = {"trauma": 0, "regional": 1, "local_center": 2, "local": 3, "unknown": 4}
    return sorted(rows, key=lambda r: (r["region"], order[r["classCode"]], r["name"]))


HISTORY_RETENTION_DAYS = 365


def rounded(value):
    return None if value is None else round(value, 1)


def merge_saturation(existing, prefix, value):
    """Accumulate one day's samples while keeping the public field as daily average."""
    count_key = f"{prefix}_sample_count"
    sum_key = f"{prefix}_saturation_sum"
    avg_key = f"{prefix}_saturation_avg"
    min_key = f"{prefix}_saturation_min"
    max_key = f"{prefix}_saturation_max"
    public_key = f"{prefix}_saturation"
    if value is None:
        return
    old_count = existing.get(count_key)
    old_avg = existing.get(avg_key, existing.get(public_key))
    if old_count is None:
        # A legacy public saturation value represents one historical snapshot.
        old_count = 1 if old_avg is not None else 0
    old_sum = existing.get(sum_key)
    if old_sum is None:
        old_sum = (old_avg or 0) * old_count
    old_min = existing.get(min_key, old_avg if old_count else None)
    old_max = existing.get(max_key, old_avg if old_count else None)
    new_count = old_count + 1
    new_sum = old_sum + value
    new_avg = new_sum / new_count
    existing[count_key] = new_count
    existing[sum_key] = round(new_sum, 4)
    existing[avg_key] = rounded(new_avg)
    existing[min_key] = rounded(
        value if old_min is None else min(old_min, value)
    )
    existing[max_key] = rounded(
        value if old_max is None else max(old_max, value)
    )
    existing[public_key] = existing[avg_key]


def merge_national_saturation(existing, value):
    if value is None:
        return
    old_count = existing.get("sample_count")
    old_avg = existing.get("saturation_avg", existing.get("saturation"))
    if old_count is None:
        old_count = 1 if old_avg is not None else 0
    old_sum = existing.get("saturation_sum")
    if old_sum is None:
        old_sum = (old_avg or 0) * old_count
    old_min = existing.get("saturation_min", old_avg if old_count else None)
    old_max = existing.get("saturation_max", old_avg if old_count else None)
    new_count = old_count + 1
    new_sum = old_sum + value
    new_avg = new_sum / new_count
    existing["sample_count"] = new_count
    existing["saturation_sum"] = round(new_sum, 4)
    existing["saturation_avg"] = rounded(new_avg)
    existing["saturation_min"] = rounded(
        value if old_min is None else min(old_min, value)
    )
    existing["saturation_max"] = rounded(
        value if old_max is None else max(old_max, value)
    )
    existing["saturation"] = existing["saturation_avg"]


def update_history(history, rows, captured_at):
    """일자별 기록을 갱신한다.

    30분 주기 수집값이 하루 안에서 사라지지 않도록 기관별·일자별로
    평균, 최소, 최대 포화도와 샘플 수를 누적한다. 병상 수와 메시지는 최신
    스냅샷을 보관하고, 보존 기간을 넘긴 기록은 파일 크기 무한 증식을 막기 위해 잘라낸다.
    """
    today = kst_date(captured_at)
    cutoff = (
        parse_timestamp(captured_at).astimezone(KST).date()
        - timedelta(days=HISTORY_RETENTION_DAYS)
    ).isoformat()
    by_key = {
        (row["date"], row["code"]): row for row in history if row["date"] >= cutoff
    }

    for row in rows:
        key = (today, row["code"])
        existing = by_key.get(key)
        if existing and existing.get("schema_version", 1) < HISTORY_SCHEMA_VERSION:
            # Do not merge a legacy UTC-day accumulator into the first KST day.
            existing = None
        if existing is None:
            existing = {
                "date": today,
                "region": row["region"],
                "code": row["code"],
                "name": row["name"],
                "type": row["type"],
                "grade": row["grade"],
                "first_sample_at": captured_at,
            }
        existing.update(
            {
                "schema_version": HISTORY_SCHEMA_VERSION,
                "date_basis": HISTORY_DATE_BASIS,
                "aggregation": HISTORY_AGGREGATION,
                "region": row["region"],
                "name": row["name"],
                "type": row["type"],
                "grade": row["grade"],
                "general_available": row["general_available"],
                "general_total": row["general_total"],
                "child_available": row["child_available"],
                "child_total": row["child_total"],
                "updated_at": captured_at,
                "last_sample_at": captured_at,
            }
        )
        merge_saturation(existing, "general", row["general_saturation"])
        merge_saturation(existing, "child", row["child_saturation"])
        by_key[key] = existing
    return [by_key[key] for key in sorted(by_key)]


def update_national_history(history, rows, captured_at):
    """내 손안의 응급실 전국 전체 기관의 일자별 평균·최소·최대 포화도를 저장한다."""
    today = kst_date(captured_at)
    cutoff = (
        parse_timestamp(captured_at).astimezone(KST).date()
        - timedelta(days=HISTORY_RETENTION_DAYS)
    ).isoformat()
    by_key = {
        (row["date"], row["code"]): row for row in history if row["date"] >= cutoff
    }

    for row in rows:
        code = row.get("c") or f'{row["r"]}|{row["n"]}'
        key = (today, code)
        existing = by_key.get(key)
        if existing and existing.get("schema_version", 1) < HISTORY_SCHEMA_VERSION:
            existing = None
        if existing is None:
            existing = {
                "date": today,
                "region": row["r"],
                "code": code,
                "name": row["n"],
                "type": row["t"],
                "first_sample_at": captured_at,
            }
        existing.update(
            {
                "schema_version": HISTORY_SCHEMA_VERSION,
                "date_basis": HISTORY_DATE_BASIS,
                "aggregation": HISTORY_AGGREGATION,
                "region": row["r"],
                "name": row["n"],
                "type": row["t"],
                "available": row["a"],
                "total": row["o"],
                "message_count": row["m"],
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "address": row.get("addr", ""),
                "updated_at": captured_at,
                "last_sample_at": captured_at,
            }
        )
        merge_national_saturation(existing, row["s"])
        by_key[key] = existing
    return [by_key[key] for key in sorted(by_key)]


def build_stale_national_meta(
    previous_meta,
    captured_at,
    failed_labels,
    successful_region_count,
    attempt_quality,
):
    """Preserve last complete snapshot metadata and record a failed attempt separately."""
    meta = dict(previous_meta or {})
    meta.update(
        {
            "last_attempt_at": captured_at,
            "snapshot_status": "stale_partial_failure",
            "last_attempt_failed": list(failed_labels),
            "last_attempt_successful_region_count": successful_region_count,
            "last_attempt_quality": dict(attempt_quality),
        }
    )
    return meta


def archive_national_daily(history, latest_rows, captured_at, quality):
    """Write a date-partitioned, research-ready daily aggregate without pruning old days."""
    today = kst_date(captured_at)
    latest_codes = {row.get("c") for row in latest_rows if row.get("c")}
    expected = quality.get("unique_institution_count")
    if expected is not None and len(latest_codes) != expected:
        raise RuntimeError(
            "연구용 전국 일자료 최신 기관 수 불일치: "
            f"latest={len(latest_codes)} expected={expected}"
        )
    records = [
        row
        for row in history
        if row.get("date") == today
        and row.get("schema_version") == HISTORY_SCHEMA_VERSION
        and row.get("date_basis") == HISTORY_DATE_BASIS
    ]
    records.sort(key=lambda row: (row.get("region", ""), row.get("code", "")))

    institutions = [
        {
            "code": row.get("code"),
            "region": row.get("region"),
            "name": row.get("name"),
            "type": row.get("type"),
            "available_last": row.get("available"),
            "total_last": row.get("total"),
            "saturation_mean": row.get("saturation_avg"),
            "saturation_min": row.get("saturation_min"),
            "saturation_max": row.get("saturation_max"),
            "sample_count": row.get("sample_count", 0),
            "message_count_last": row.get("message_count"),
            "latitude": row.get("lat"),
            "longitude": row.get("lon"),
            "address": row.get("address", ""),
            "first_sample_at": row.get("first_sample_at"),
            "last_sample_at": row.get("last_sample_at"),
            "present_in_latest_snapshot": row.get("code") in latest_codes,
        }
        for row in records
    ]
    payload = {
        "schema_version": 1,
        "date": today,
        "timezone": HISTORY_DATE_BASIS,
        "aggregation": HISTORY_AGGREGATION,
        "complete_snapshot_only": True,
        "source_name": "NEMC 내 손안의 응급실 간편조회 API",
        "source_url": "https://mediboard.nemc.or.kr/api/v1/search/handy",
        "last_collected_at": captured_at,
        "daily_union_institution_count": len(institutions),
        "latest_snapshot_institution_count": len(latest_codes),
        "collection_quality": dict(quality),
        "institutions": institutions,
    }
    NATIONAL_RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    path = NATIONAL_RESEARCH_DIR / f"{today}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)
    return path


def archive_national_snapshot(rows, captured_at, quality):
    """Append one complete 30-minute nationwide snapshot in a compact format."""
    expected = quality.get("unique_institution_count")
    if expected is not None and len(rows) != expected:
        raise RuntimeError(
            "연구용 전국 30분 스냅샷 기관 수 불일치: "
            f"rows={len(rows)} expected={expected}"
        )
    values = [
        [
            row.get("c"),
            row.get("a"),
            row.get("o"),
            row.get("s"),
            row.get("m"),
        ]
        for row in sorted(rows, key=lambda row: row.get("c") or "")
    ]
    payload = {
        "schema_version": 1,
        "captured_at": captured_at,
        "timezone": HISTORY_DATE_BASIS,
        "complete_snapshot_only": True,
        "source_name": "NEMC 내 손안의 응급실 간편조회 API",
        "source_url": "https://mediboard.nemc.or.kr/api/v1/search/handy",
        "institution_count": len(values),
        "collection_quality": dict(quality),
        "columns": [
            "institution_code",
            "available",
            "total",
            "saturation",
            "message_count",
        ],
        "values": values,
    }
    NATIONAL_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = NATIONAL_SNAPSHOT_DIR / f"{kst_date(captured_at)}.jsonl"
    existing_lines = []
    captured_values = set()
    if path.exists():
        existing_lines = [
            line for line in path.read_text(encoding="utf-8").splitlines() if line
        ]
        for line in existing_lines:
            saved = json.loads(line)
            captured_values.add(saved.get("captured_at"))
    if captured_at not in captured_values:
        existing_lines.append(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
    temporary = path.with_suffix(".jsonl.tmp")
    temporary.write_text(
        "\n".join(existing_lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)
    return path


def summary(rows):
    def known(kind):
        return [row for row in rows if row[f"{kind}_available"] is not None and row[f"{kind}_total"]]

    general = known("general")
    child = known("child")
    general_reported_available = sum(row["general_available"] for row in general)
    general_available = sum(max(0, row["general_available"]) for row in general)
    general_overflow = sum(max(0, -row["general_available"]) for row in general)
    general_total = sum(row["general_total"] for row in general)
    child_reported_available = sum(row["child_available"] for row in child)
    child_available = sum(max(0, row["child_available"]) for row in child)
    child_overflow = sum(max(0, -row["child_available"]) for row in child)
    child_total = sum(row["child_total"] for row in child)
    return {
        "total": len(rows),
        "gwangju": sum(1 for row in rows if row["region"] == "광주"),
        "jeonnam": sum(1 for row in rows if row["region"] == "전남"),
        "general_available": general_available,
        "general_overflow": general_overflow,
        "general_total": general_total,
        "general_saturation": percent(general_reported_available, general_total),
        "child_available": child_available,
        "child_overflow": child_overflow,
        "child_total": child_total,
        "child_saturation": percent(child_reported_available, child_total),
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
    source = re.sub(
        r"병원별 추이 버튼을 누르면 .*?확인할 수 있습니다\.",
        "병원별 추이 버튼을 누르면 30분 주기로 갱신되는 최신 병상 현황과 저장된 일자별 포화도 그래프를 확인할 수 있습니다.",
        source,
        count=1,
    )
    # 과거 버전이 매 실행마다 동일 문구를 중복 삽입하던 버그가 있어, 반복을 1회로 정규화한다(멱등)
    source = re.sub(
        r"(?:(?:2시간마다|외부 cron으로 주기) 갱신되는 최신 병상 현황과 )+",
        "30분 주기로 갱신되는 최신 병상 현황과 ",
        source,
        count=1,
    )
    source = re.sub(
        r'<div class="card"><strong>\d+</strong><span>응급의료기관 등<br>광주 \d+ / 전남 \d+</span></div>',
        f'<div class="card"><strong>{stats["total"]}</strong><span>응급의료기관 등<br>광주 {stats["gwangju"]} / 전남 {stats["jeonnam"]}</span></div>',
        source,
        count=1,
    )
    source = re.sub(
        r'<div class="card"><strong>남은 [^<]+ / 전체 [^<]+</strong><span>일반 응급실 (?:남은 병상|비음수 빈 병상 합)/전체 병상<br>실시간 포화 [^<]+</span></div>',
        f'<div class="card"><strong>남은 {stats["general_available"]} / 전체 {stats["general_total"]}</strong><span>일반 응급실 비음수 빈 병상 합/전체 병상<br>실시간 포화 {stats["general_saturation"]}%'
        + (
            f' · 초과 보고 {stats["general_overflow"]}병상'
            if stats["general_overflow"]
            else ""
        )
        + "</span></div>",
        source,
        count=1,
    )
    source = re.sub(
        r'<div class="card"><strong>남은 [^<]+ / 전체 [^<]+</strong><span>소아 응급실 (?:남은 병상|비음수 빈 병상 합)/전체 병상<br>실시간 포화 [^<]+</span></div>',
        f'<div class="card"><strong>남은 {stats["child_available"]} / 전체 {stats["child_total"]}</strong><span>소아 응급실 비음수 빈 병상 합/전체 병상<br>실시간 포화 {stats["child_saturation"]}%'
        + (
            f' · 초과 보고 {stats["child_overflow"]}병상'
            if stats["child_overflow"]
            else ""
        )
        + "</span></div>",
        source,
        count=1,
    )
    source = re.sub(
        r'<div class="card"><strong>A \d+ / B \d+ / C \d+</strong><span>2024 평가등급<br>미분류 \d+</span></div>',
        f'<div class="card"><strong>A {stats["grades"]["A"]} / B {stats["grades"]["B"]} / C {stats["grades"]["C"]}</strong><span>2024 평가등급<br>미분류 {stats["grades"]["-"]}</span></div>',
        source,
        count=1,
    )
    return source


def update_index_cache_buster(captured_at):
    source = INDEX_HTML.read_text(encoding="utf-8")
    version = re.sub(r"[^0-9]", "", captured_at)[:14]
    updated = re.sub(
        r'(src|href)="gwangju_emergency_map\.html(?:\?v=[^"]*)?"',
        rf'\1="gwangju_emergency_map.html?v={version}"',
        source,
    )
    INDEX_HTML.write_text(updated, encoding="utf-8", newline="\n")


def main():
    source = MAP_HTML.read_text(encoding="utf-8")
    previous_data = extract_array(source, "DATA")
    history = extract_array(source, "HISTORY")
    national_history = extract_array(source, "NATIONAL_HISTORY")
    national_meta = extract_array(source, "NATMETA")
    previous_by_code = {row["code"]: row for row in previous_data}
    items_by_code, failed_labels = fetch_all_regions()
    rows = fetch_rows(previous_by_code, items_by_code.get("12"))
    (
        nat_rows,
        nat_total,
        nat_failed,
        successful_region_count,
        nat_history_rows,
        nat_quality,
    ) = fetch_national(items_by_code, failed_labels)
    captured_at = capture_timestamp()
    history = update_history(history, rows, captured_at)
    stats = summary(rows)
    source = replace_array(source, "DATA", rows)
    source = replace_array(source, "HISTORY", history)
    national_complete = (
        successful_region_count == len(NATIONAL_CODES) and not nat_failed
    )
    daily_archive_path = None
    snapshot_archive_path = None
    if national_complete:
        national_history = update_national_history(national_history, nat_history_rows, captured_at)
        source = replace_array(source, "NATIONAL", nat_rows)
        source = replace_array(source, "NATIONAL_HISTORY", national_history)
        source = replace_array(
            source,
            "NATMETA",
            [
                {
                    "schema_version": HISTORY_SCHEMA_VERSION,
                    "collector_version": 2,
                    "source_name": "NEMC 내 손안의 응급실 간편조회 API",
                    "source_url": "https://mediboard.nemc.or.kr/api/v1/search/handy",
                    "captured": captured_at,
                    "source_updated_at": None,
                    "timezone": HISTORY_DATE_BASIS,
                    "date_basis": HISTORY_DATE_BASIS,
                    "aggregation": HISTORY_AGGREGATION,
                    "snapshot_status": "complete",
                    "total": nat_total,
                    "failed": nat_failed,
                    "successful_region_count": successful_region_count,
                    **nat_quality,
                }
            ],
        )
        snapshot_archive_path = archive_national_snapshot(
            nat_history_rows,
            captured_at,
            nat_quality,
        )
        daily_archive_path = archive_national_daily(
            national_history,
            nat_history_rows,
            captured_at,
            nat_quality,
        )
    else:
        # A partial nationwide fetch must never replace the last complete snapshot.
        previous_meta = build_stale_national_meta(
            national_meta[0] if national_meta else {},
            captured_at,
            nat_failed,
            successful_region_count,
            nat_quality,
        )
        source = replace_array(source, "NATMETA", [previous_meta])
    source = update_static_text(source, captured_at, stats)
    MAP_HTML.write_text(source, encoding="utf-8", newline="\n")
    update_index_cache_buster(captured_at)
    print(
        "updated "
        f"{MAP_HTML.name}: rows={stats['total']} "
        f"general={stats['general_available']}/{stats['general_total']} "
        f"child={stats['child_available']}/{stats['child_total']} "
        f"national>={NATIONAL_THRESHOLD}%: {len(nat_rows)}/{nat_total} "
        f"(snapshot={'complete' if national_complete else 'preserved-previous'}) "
        f"(duplicates={nat_quality['duplicate_count']}, "
        f"conflicts={nat_quality['conflicting_duplicate_count']}) "
        f"(failed_regions={nat_failed or 'none'}) "
        f"(snapshot_archive={snapshot_archive_path.relative_to(ROOT) if snapshot_archive_path else 'unchanged'}) "
        f"(daily_archive={daily_archive_path.relative_to(ROOT) if daily_archive_path else 'unchanged'}) "
        f"captured_at={captured_at}"
    )


if __name__ == "__main__":
    main()
