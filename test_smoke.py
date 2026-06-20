#!/usr/bin/env python3
"""Smoke test: run SQL→RE on test files and verify outputs."""

import json
import re
import sys
import tempfile
from pathlib import Path

# Add project root
PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))

from sql_to_re import SQLParser, REDiagramGenerator


def test_parse_single_statement():
    sql = """SELECT a.uid, a.name
FROM sng_db::user_table a
LEFT JOIN dim_db::info_table b ON a.uid = b.uid
WHERE a.ftime = '20260619'"""
    parser = SQLParser()
    results = parser.parse_file(str(PROJ / "test.sql"))  # use existing file
    assert len(results) >= 1, "Should parse at least one statement"
    for r in results:
        assert "tables" in r, "Result must contain tables"
        assert "relationships" in r, "Result must contain relationships"
        for t in r["tables"]:
            assert "key" in t, "Table must have key"
            assert "db" in t, "Table must have db"
            assert "table" in t, "Table must have table name"
            assert "fields" in t, "Table must have fields"
    print(f"  [OK] parse_single: {len(results)} stmt(s), "
          f"{sum(len(r['tables']) for r in results)} tables total")


def test_parse_multi_statements():
    parser = SQLParser()
    results = parser.parse_file(str(PROJ / "test_multi.sql"))
    assert len(results) == 2, f"Expected 2 statements, got {len(results)}"
    tables_seen = set()
    for i, r in enumerate(results):
        for t in r["tables"]:
            tables_seen.add(t["key"])
    assert "dwd.user_action" in tables_seen, "Should find user_action in multi"
    print(f"  [OK] parse_multi: {len(results)} stmts, {len(tables_seen)} unique tables")


def test_generate_html():
    parser = SQLParser()
    generator = REDiagramGenerator()
    results = parser.parse_file(str(PROJ / "test.sql"))
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = str(Path(tmpdir) / "out.html")
        generator.generate(results, out_path)
        html = Path(out_path).read_text(encoding="utf-8")
        assert "DOCTYPE html" in html, "Output must be HTML"
        assert "const DATA" in html, "Output must embed DATA JSON"
        assert "getMergedData" in html, "Must include merge function"
        assert "全部合并" in html or "全部合" in html, "Must include merge button text"
    print(f"  [OK] generate_html: valid HTML with merged view support")


def test_relationships():
    parser = SQLParser()
    results = parser.parse_file(str(PROJ / "test.sql"))
    r = results[0]
    assert len(r["relationships"]) == 2, \
        f"Expected 2 relationships, got {len(r['relationships'])}"
    join_types = {rel["join_type"] for rel in r["relationships"]}
    assert "LEFT JOIN" in join_types, "Expected LEFT JOIN"
    print(f"  [OK] relationships: {len(r['relationships'])} rels, types={join_types}")


def test_fields():
    parser = SQLParser()
    results = parser.parse_file(str(PROJ / "test.sql"))
    r = results[0]
    # qmkg_user_passive_features_rd should have uid, active_level, passive_type
    for t in r["tables"]:
        if t["table"] == "qmkg_user_passive_features_rd":
            names = {f["name"] for f in t["fields"]}
            assert "uid" in names, "Missing uid field"
            assert "active_level" in names, "Missing active_level field"
            assert "passive_type" in names, "Missing passive_type field"
            print(f"  [OK] fields: {t['table']} has {len(t['fields'])} fields: {names}")
            return
    assert False, "Table qmkg_user_passive_features_rd not found"


if __name__ == "__main__":
    print("=== SQL → RE Diagram Generator: Smoke Test ===\n")
    test_parse_single_statement()
    test_parse_multi_statements()
    test_relationships()
    test_fields()
    test_generate_html()
    print("\n=== All tests passed ===")
