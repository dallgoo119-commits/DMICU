"""One-time lossless extraction of inline history. No new API observations."""
import re
import update_emergency_map as updater


def main():
    source = updater.MAP_HTML.read_text(encoding="utf-8")
    national_history = updater.load_history(source, "NATIONAL_HISTORY")
    for name in ("HISTORY", "NATIONAL_HISTORY"):
        records = updater.load_history(source, name)
        updater.write_history(name, records)
        source = updater.replace_array(source, name, [])
        key = lambda row: (row["code"], row["date"])
        assert sorted(updater.load_history(source, name), key=key) == sorted(records, key=key)
    meta = updater.extract_array(source, "NATMETA")[0]
    current = []
    for row in national_history:
        if row.get("updated_at") != meta["captured"]:
            continue
        current.append({
            "c": row["code"], "r": row["region"], "n": row["name"],
            "t": row["type"], "a": row["available"], "o": row["total"],
            "s": updater.percent(row["available"], row["total"]),
            "m": row.get("message_count", 0), "lat": row.get("lat"),
            "lon": row.get("lon"), "addr": row.get("address", ""),
        })
    assert len(current) == meta["unique_institution_count"]
    captured = re.search(r"마지막 수집 ([0-9T:+\-.]+)", source).group(1)
    rows = updater.extract_array(source, "DATA")
    for row in rows:
        row["captured_at"] = captured
        for kind in ("general", "child"):
            row[f"{kind}_saturation"] = updater.percent(row[f"{kind}_available"], row[f"{kind}_total"])
    source = updater.replace_array(source, "DATA", rows)
    if "const NATIONAL_CURRENT=" not in source:
        source = source.replace("const HISTORY=", "const NATIONAL_CURRENT=[];\nconst LOCALMETA=[];\nconst HISTORY=", 1)
    source = updater.replace_array(source, "NATIONAL_CURRENT", current)
    source = updater.replace_array(source, "NATIONAL", sorted(
        [row for row in current if row["s"] is not None and row["s"] >= updater.NATIONAL_THRESHOLD],
        key=lambda row: (-row["s"], row["r"], row["n"]),
    ))
    source = updater.replace_array(source, "LOCALMETA", [{"captured": captured, "source_updated_at": None, **updater.summary(rows)}])
    source = updater.update_static_text(source, captured, updater.summary(rows))
    updater.MAP_HTML.write_text(source, encoding="utf-8", newline="\n")
    print(f"Extracted history without changing observations; map {len(source.encode('utf-8')):,} bytes")


if __name__ == "__main__":
    main()
