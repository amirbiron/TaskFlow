#!/usr/bin/env python3
"""
שחזור גיבוי TaskFlow למסד נתונים.

שימוש:
    python scripts/restore_backup.py backup_2026-05-03_03-00-15.zip \\
        --uri "mongodb+srv://user:pass@cluster.mongodb.net/" \\
        --db taskflow

ברירת מחדל: כותב לאותו DB ששמור ב-_meta.json של הגיבוי.

האם זה מוחק דאטה קיים?
    --mode replace  → drop ל-collection ואז insert (ברירת מחדל)
    --mode upsert   → upsert לפי _id (משלב עם דאטה קיים)
    --mode skip     → לא מוחק; רק מוסיף אם ה-collection ריק

תלויות: pip install pymongo
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

try:
    from bson import json_util
    from pymongo import MongoClient, ReplaceOne
except ImportError:
    print("ERROR: חסר pymongo. הרץ: pip install pymongo", file=sys.stderr)
    sys.exit(1)


def load_meta(zf: zipfile.ZipFile) -> dict:
    """טוען את _meta.json מהארכיון. נכשל אם חסר - גיבוי לא תקף."""
    try:
        with zf.open("_meta.json") as f:
            return json.load(f)
    except KeyError:
        raise SystemExit("ERROR: _meta.json חסר בארכיון - לא קובץ גיבוי תקין")


def restore_collection(db, coll_name: str, docs: list, mode: str) -> int:
    """משחזר collection בודד לפי mode. מחזיר כמה רשומות נכתבו."""
    coll = db[coll_name]

    if mode == "replace":
        coll.drop()
        if docs:
            coll.insert_many(docs)
        return len(docs)

    if mode == "upsert":
        if not docs:
            return 0
        ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs]
        result = coll.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    if mode == "skip":
        if coll.estimated_document_count() > 0:
            print(f"  [skip] {coll_name} - כבר מכיל דאטה", file=sys.stderr)
            return 0
        if docs:
            coll.insert_many(docs)
        return len(docs)

    raise ValueError(f"mode לא חוקי: {mode}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("backup_file", help="נתיב לקובץ הגיבוי .zip")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default=None, help="שם מסד היעד (ברירת מחדל: לפי _meta.json)")
    parser.add_argument(
        "--mode",
        choices=["replace", "upsert", "skip"],
        default="replace",
        help="אסטרטגיית כתיבה (ברירת מחדל: replace - מוחק קיים)",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="COLL",
        help="שחזור רק של ה-collections האלה (אחרת - הכל)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="דלג על אישור אינטראקטיבי",
    )
    args = parser.parse_args()

    backup_path = Path(args.backup_file)
    if not backup_path.is_file():
        sys.exit(f"ERROR: קובץ לא קיים: {backup_path}")

    with zipfile.ZipFile(backup_path, "r") as zf:
        meta = load_meta(zf)
        target_db_name = args.db or meta.get("database_name")
        if not target_db_name:
            sys.exit("ERROR: חייב להעביר --db (לא נמצא database_name ב-meta)")

        print(f"גיבוי: {backup_path.name}")
        print(f"  נוצר ב: {meta.get('created_at')}")
        print(f"  מסד מקור: {meta.get('database_name')}")
        print(f"  מסד יעד:  {target_db_name}")
        print(f"  מצב:      {args.mode}")
        print(f"  collections: {len(meta.get('collections', {}))}")
        for c, count in meta.get("collections", {}).items():
            marker = " *" if (args.only and c not in args.only) else ""
            print(f"    {c}: {count} רשומות{marker}")
        if args.only:
            print(f"  (* = ידולג, רק {args.only} ישוחזרו)")

        if not args.yes:
            ans = input("\nלהמשיך? [y/N] ").strip().lower()
            if ans != "y":
                sys.exit("בוטל.")

        client = MongoClient(args.uri)
        db = client[target_db_name]

        total_written = 0
        for coll_name in meta.get("collections", {}):
            if args.only and coll_name not in args.only:
                continue
            try:
                with zf.open(f"{coll_name}.json") as f:
                    docs = json_util.loads(f.read().decode("utf-8"))
            except KeyError:
                print(f"  [warn] {coll_name}.json חסר - מדלג", file=sys.stderr)
                continue
            written = restore_collection(db, coll_name, docs, args.mode)
            total_written += written
            print(f"  ✓ {coll_name}: {written} רשומות")

        print(f"\nהושלם. סך הכל {total_written} רשומות נכתבו ל-{target_db_name}.")


if __name__ == "__main__":
    main()
