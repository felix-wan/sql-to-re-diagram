#!/usr/bin/env python3
"""
SQL → RE Diagram Generator
Parses SQL files to extract database/table/field relationships and
generates an interactive HTML relationship diagram.
"""

import re
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class TableInfo:
    """Represents a table with its database, fields, and relationships."""

    def __init__(self, db: str, table: str, alias: str = ""):
        self.db = db
        self.table = table
        self.alias = alias or ""
        self.fields: Dict[str, str] = {}  # field_name -> comment
        self.relationships: List[Dict] = []  # {target_table, target_field, source_field, join_type}

    @property
    def full_name(self) -> str:
        return f"{self.db}::{self.table}"

    @property
    def display_name(self) -> str:
        return f"{self.table}"

    @property
    def unique_key(self) -> str:
        return f"{self.db}.{self.table}"


class SQLParser:
    """Parses SQL statements to extract schema metadata."""

    # SQL keywords that should never be treated as table aliases
    SQL_KEYWORDS = frozenset({
        'AS', 'ON', 'AND', 'OR', 'NOT', 'IN', 'WHERE',
        'LEFT', 'RIGHT', 'INNER', 'OUTER', 'CROSS', 'FULL',
        'JOIN', 'GROUP', 'ORDER', 'BY', 'HAVING',
        'LIMIT', 'OFFSET', 'UNION', 'ALL', 'SELECT',
        'FROM', 'WHEN', 'THEN', 'ELSE', 'END',
        'CASE', 'IS', 'NULL', 'BETWEEN', 'LIKE',
        'EXISTS', 'DISTINCT', 'TOP', 'WITH',
        'PARTITION', 'CLUSTER', 'SORT', 'DISTRIBUTE',
    })

    def __init__(self):
        self.tables: Dict[str, TableInfo] = {}
        self.alias_map: Dict[str, str] = {}  # alias -> unique_key
        self.current_statement = 0

    def parse_file(self, filepath: str) -> List[Dict]:
        """Parse a SQL file and return structured data for RE diagram."""
        content = Path(filepath).read_text(encoding="utf-8")
        statements = self._split_statements(content)
        results = []
        for stmt in statements:
            stmt = stmt.strip()
            if stmt:
                self.current_statement += 1
                result = self._parse_statement(stmt)
                if result:
                    results.append(result)
        return results

    def _split_statements(self, content: str) -> List[str]:
        """Split SQL content into individual statements, handling strings and parens."""
        statements = []
        current = []
        depth = 0
        in_string = False
        string_char = None

        for char in content:
            if in_string:
                current.append(char)
                if char == string_char:
                    in_string = False
            elif char in ("'", '"'):
                in_string = True
                string_char = char
                current.append(char)
            elif char == '(':
                depth += 1
                current.append(char)
            elif char == ')':
                depth -= 1
                current.append(char)
            elif char == ';' and depth == 0:
                stmt = ''.join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
            else:
                current.append(char)

        remaining = ''.join(current).strip()
        if remaining:
            statements.append(remaining)
        return statements

    def _tokenize_sql(self, sql: str) -> List[str]:
        """Tokenize SQL preserving important structure."""
        # Normalize whitespace and newlines
        sql = re.sub(r'\s+', ' ', sql).strip()
        # Add spaces around parens and operators for easier tokenization
        sql = re.sub(r'([()=,;])', r' \1 ', sql)
        tokens = sql.split()
        return tokens

    def _parse_statement(self, sql: str) -> Optional[Dict]:
        """Parse a single SQL statement."""
        self.tables = {}
        self.alias_map = {}

        # Work with normalized SQL
        sql_norm = re.sub(r'\s+', ' ', sql).strip()

        # Extract tables from FROM and JOIN clauses
        self._extract_tables(sql_norm)

        # Extract aliases from subquery closures
        self._extract_subquery_aliases(sql_norm)

        # Extract relationships from JOIN conditions
        self._extract_relationships(sql_norm)

        # Extract fields from SELECT and other clauses
        self._extract_fields(sql_norm)

        return self._build_result(sql_norm)

    def _extract_tables(self, sql: str):
        """Extract all database::table references and their aliases."""
        # Pattern 1: FROM/JOIN database::table [PARTITION(...)] [alias]
        # Pattern 2: FROM/JOIN schema.table [PARTITION(...)] [alias]
        # Pattern 3: FROM/JOIN table [PARTITION(...)] [alias]
        table_pattern = re.compile(
            r'(?:FROM|JOIN)\s+'
            r'([a-zA-Z_][a-zA-Z0-9_]*(?:::[a-zA-Z_][a-zA-Z0-9_]*)?(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)'  # table ref
            r'(?:\s+PARTITION\s*\([^)]*\))?'  # optional PARTITION hint
            r'(?:\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?',  # optional alias
            re.IGNORECASE
        )

        for match in table_pattern.finditer(sql):
            table_ref = match.group(1)
            alias_candidate = match.group(2)

            # Resolve table reference
            if '::' in table_ref:
                db, table = table_ref.split('::', 1)
            elif '.' in table_ref:
                parts = table_ref.split('.', 1)
                db, table = parts[0], parts[1]
            else:
                db = "default"
                table = table_ref

            key = f"{db}.{table}"
            if key not in self.tables:
                self.tables[key] = TableInfo(db, table)

            # Check if alias candidate is valid (not a SQL keyword)
            if alias_candidate and alias_candidate.upper() not in self.SQL_KEYWORDS:
                self.alias_map[alias_candidate] = key
                self.tables[key].alias = alias_candidate

        # Also find tables inside subqueries: FROM (SELECT ... FROM db::table ...)
        # Handle nested subquery references
        self._extract_subquery_tables(sql)

    def _extract_subquery_tables(self, sql: str):
        """Extract tables from within subqueries."""
        # Find SELECT inside parentheses
        depth = 0
        i = 0
        while i < len(sql):
            if sql[i] == '(':
                start = i
                depth = 1
                j = i + 1
                while j < len(sql) and depth > 0:
                    if sql[j] == '(':
                        depth += 1
                    elif sql[j] == ')':
                        depth -= 1
                    j += 1
                inner = sql[start+1:j-1]
                # Recursively extract tables from subquery
                if re.search(r'\bFROM\b', inner, re.IGNORECASE):
                    self._extract_tables(inner)
                i = j
            else:
                i += 1

    def _extract_subquery_aliases(self, sql: str):
        """Extract aliases from subquery closures: ) alias ON/JOIN/WHERE...
        Map subquery aliases to tables inside the subquery when unambiguous.
        """
        subq_pattern = re.compile(
            r'\)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+'  # )alias (with or without space)
            r'(?=LEFT|RIGHT|INNER|OUTER|CROSS|FULL|JOIN|ON|WHERE|GROUP|ORDER|LIMIT|HAVING|UNION|$)', 
            re.IGNORECASE
        )

        for match in subq_pattern.finditer(sql):
            alias = match.group(1)
            if alias.upper() in self.SQL_KEYWORDS or alias in self.alias_map:
                continue

            # Find the subquery content by matching parens backwards
            end_pos = match.start()
            depth = 1
            pos = end_pos - 1
            while pos >= 0 and depth > 0:
                if sql[pos] == ')':
                    depth += 1
                elif sql[pos] == '(':
                    depth -= 1
                pos -= 1

            if depth == 0:
                inner = sql[pos+2:end_pos-1]  # content inside the parens
                # Find tables referenced in this subquery
                inner_tables = re.findall(
                    r'([a-zA-Z_][a-zA-Z0-9_]*(?:::[a-zA-Z_][a-zA-Z0-9_]*)?(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)',
                    inner
                )
                for t in inner_tables:
                    if '::' in t:
                        db, table = t.split('::', 1)
                    elif '.' in t and not t.startswith('('):
                        parts = t.split('.', 1)
                        db, table = parts[0], parts[1]
                    else:
                        continue
                    key = f"{db}.{table}"
                    if key in self.tables:
                        self.alias_map[alias] = key
                        self.tables[key].alias = alias
                        break  # Use first table found as the alias target

    def _extract_relationships(self, sql: str):
        """Extract JOIN conditions between tables."""
        # Normalize: collapse spaces around ON and = for easier matching
        # Find each JOIN ... ON ... segment
        # Pattern: walk through JOIN clauses

        # Strategy: find all table.field = table.field patterns 
        # that appear after ON keywords
        on_sections = re.split(r'\bON\b', sql, flags=re.IGNORECASE)
        if len(on_sections) < 2:
            return

        # For each ON section, the first part is the ON clause content
        # (before next JOIN/WHERE/GROUP/ORDER/LIMIT)
        for i in range(1, len(on_sections)):
            on_content = on_sections[i]
            # Find where this ON section ends
            end_match = re.search(
                r'\b(LEFT|RIGHT|INNER|OUTER|CROSS|FULL|JOIN|WHERE|GROUP|ORDER|LIMIT|HAVING|UNION)\b',
                on_content, re.IGNORECASE
            )
            if end_match:
                on_content = on_content[:end_match.start()]

            # Extract field = field conditions
            # Handle: alias.field = alias.field [AND alias.field = alias.field ...]
            cond_pattern = re.compile(
                r'([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)',
                re.IGNORECASE
            )

            for match in cond_pattern.finditer(on_content):
                left_alias = match.group(1)
                left_field = match.group(2)
                right_alias = match.group(3)
                right_field = match.group(4)

                left_key = self._resolve_alias(left_alias)
                right_key = self._resolve_alias(right_alias)

                if left_key and right_key and left_key in self.tables and right_key in self.tables:
                    join_type = self._get_join_type(sql, on_sections, i)

                    # Determine direction based on which is the "driving" table
                    # For LEFT JOIN, the left table is the driver
                    if join_type == 'LEFT JOIN':
                        self.tables[left_key].relationships.append({
                            "target_table": right_key,
                            "target_field": right_field,
                            "source_field": left_field,
                            "join_type": join_type,
                        })
                    else:
                        self.tables[left_key].relationships.append({
                            "target_table": right_key,
                            "target_field": right_field,
                            "source_field": left_field,
                            "join_type": join_type,
                        })

    def _get_join_type(self, sql: str, on_sections: List[str], on_idx: int) -> str:
        """Determine the JOIN type for an ON clause.

        We look at the text between on_sections[on_idx-1] and on_sections[on_idx].
        The JOIN keyword appears right before the ON keyword.
        """
        # The text just before this ON is in the previous section
        prev_section = on_sections[on_idx - 1]
        # Look for JOIN keyword near the end of the previous section
        # Get the last 200 chars of the previous section
        tail = prev_section[-200:].upper()
        
        if 'LEFT OUTER JOIN' in tail or 'LEFT JOIN' in tail:
            return 'LEFT JOIN'
        elif 'RIGHT OUTER JOIN' in tail or 'RIGHT JOIN' in tail:
            return 'RIGHT JOIN'
        elif 'FULL OUTER JOIN' in tail or 'FULL JOIN' in tail:
            return 'FULL JOIN'
        elif 'CROSS JOIN' in tail:
            return 'CROSS JOIN'
        elif 'INNER JOIN' in tail:
            return 'INNER JOIN'
        elif 'JOIN' in tail:
            return 'INNER JOIN'
        return 'JOIN'

    def _parse_field_ref(self, expr: str) -> Optional[Tuple[str, str]]:
        """Parse a field reference like 'a.uid' or 'b.algorithm_id'."""
        expr = expr.strip().rstrip(',')
        match = re.match(r'([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)(?:\s|$)', expr)
        if match:
            return (match.group(1), match.group(2))
        return None

    def _resolve_alias(self, alias: str) -> Optional[str]:
        """Resolve a table alias to its unique key."""
        if alias in self.alias_map:
            return self.alias_map[alias]
        # If no alias mapping, try exact match on table alias
        for key, table in self.tables.items():
            if table.alias == alias:
                return key
        return None

    def _extract_fields(self, sql: str):
        """Extract selected fields for each table based on alias prefix."""
        # Find the SELECT clause
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if not select_match:
            return

        select_content = select_match.group(1)

        # Extract alias.field references
        field_pattern = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_*][a-zA-Z0-9_]*)')
        for match in field_pattern.finditer(select_content):
            alias = match.group(1)
            field = match.group(2)
            table_key = self._resolve_alias(alias)
            if table_key and table_key in self.tables:
                if field not in self.tables[table_key].fields:
                    self.tables[table_key].fields[field] = ""

        # Extract fields from JOIN conditions (relationships)
        for table_key, table_info in self.tables.items():
            for rel in table_info.relationships:
                sf = rel["source_field"]
                tf = rel["target_field"]
                if sf not in self.tables[table_key].fields:
                    self.tables[table_key].fields[sf] = ""
                target_info = self.tables.get(rel["target_table"])
                if target_info and tf not in target_info.fields:
                    target_info.fields[tf] = ""

        # Extract fields from WHERE, GROUP BY, ORDER BY
        clause_patterns = [
            (r'WHERE\s+(.*?)(?:GROUP|ORDER|HAVING|LIMIT|$)', re.IGNORECASE | re.DOTALL),
            (r'GROUP\s+BY\s+(.*?)(?:ORDER|HAVING|LIMIT|$)', re.IGNORECASE | re.DOTALL),
            (r'ORDER\s+BY\s+(.*?)(?:LIMIT|$)', re.IGNORECASE | re.DOTALL),
        ]
        for pattern, flags in clause_patterns:
            clause_match = re.search(pattern, sql, flags)
            if clause_match:
                content = clause_match.group(1)
                for match in field_pattern.finditer(content):
                    alias = match.group(1)
                    field = match.group(2)
                    table_key = self._resolve_alias(alias)
                    if table_key and table_key in self.tables and field not in self.tables[table_key].fields:
                        self.tables[table_key].fields[field] = ""

    def _build_result(self, sql: str) -> Dict:
        """Build the structured result."""
        databases = {}
        tables_list = []
        relationships_list = []

        for key, table_info in self.tables.items():
            db_name = table_info.db
            if db_name not in databases:
                databases[db_name] = {"name": db_name, "tables": []}

            # Build per-table relationships (forward)
            table_rels = []
            for rel in table_info.relationships:
                table_rels.append({
                    "target_table": rel["target_table"],
                    "source_field": rel["source_field"],
                    "target_field": rel["target_field"],
                    "join_type": rel["join_type"],
                })

            table_data = {
                "key": key,
                "db": table_info.db,
                "table": table_info.table,
                "alias": table_info.alias,
                "fields": [{"name": f, "comment": c or ""} for f, c in table_info.fields.items()],
                "relationships": table_rels,
            }
            databases[db_name]["tables"].append(table_data)
            tables_list.append(table_data)

        for key, table_info in self.tables.items():
            for rel in table_info.relationships:
                relationships_list.append({
                    "source": key,
                    "target": rel["target_table"],
                    "source_field": rel["source_field"],
                    "target_field": rel["target_field"],
                    "join_type": rel["join_type"],
                })

        return {
            "statement": self.current_statement,
            "sql": sql[:200] + "..." if len(sql) > 200 else sql,
            "databases": list(databases.values()),
            "tables": tables_list,
            "relationships": relationships_list,
        }


class REDiagramGenerator:
    """Generates an interactive HTML RE diagram from parsed data."""

    def generate(self, results: List[Dict], output_path: str):
        """Generate the HTML file."""
        data_json = json.dumps(results, ensure_ascii=False, indent=2)
        html = self._build_html(data_json)
        Path(output_path).write_text(html, encoding="utf-8")
        print(f"[OK] RE diagram generated: {output_path}")

    def _build_html(self, data_json: str) -> str:
        # Read the HTML template and substitute data
        html = HTML_TEMPLATE.replace('__DATA_JSON__', data_json)
        return html


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SQL 关系图 (RE Diagram)</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  :root {
    --bg: #f8f9fc;
    --surface: #ffffff;
    --border: #e6e8f0;
    --text: #1a1d2e;
    --text-secondary: #6b7094;
    --accent: #5b6bf7;
    --accent-light: #eef0ff;
    --green: #22c55e;
    --blue: #3b82f6;
    --orange: #f59e0b;
    --pink: #ec4899;
    --purple: #8b5cf6;
    --shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.06);
    --shadow-lg: 0 8px 40px rgba(0,0,0,0.12);
    --radius: 12px;
    --radius-sm: 8px;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    overflow: hidden;
    height: 100vh;
  }

  /* Header */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 32px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    backdrop-filter: blur(12px);
    z-index: 100;
    position: relative;
  }

  .header h1 {
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.3px;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .header h1 .badge {
    font-size: 11px;
    font-weight: 500;
    background: var(--accent-light);
    color: var(--accent);
    padding: 2px 10px;
    border-radius: 20px;
  }

  .header-controls {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .stmt-indicator {
    font-size: 13px;
    color: var(--text-secondary);
    background: var(--bg);
    padding: 6px 14px;
    border-radius: 20px;
  }

  .btn {
    padding: 8px 16px;
    border: 1px solid var(--border);
    background: var(--surface);
    border-radius: var(--radius-sm);
    font-size: 13px;
    font-weight: 500;
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.15s ease;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .btn:hover {
    border-color: var(--accent);
    color: var(--accent);
    background: var(--accent-light);
  }

  .btn-primary {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }

  .btn-primary:hover {
    background: #4a5ae6;
    color: white;
  }

  /* Main layout */
  .main {
    display: flex;
    height: calc(100vh - 62px);
  }

  /* Diagram canvas */
  .diagram-container {
    flex: 1;
    position: relative;
    overflow: hidden;
  }

  #diagram {
    width: 100%;
    height: 100%;
  }

  /* Sidebar - Table details */
  .sidebar {
    width: 0;
    overflow: hidden;
    background: var(--surface);
    border-left: 1px solid var(--border);
    transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .sidebar.open {
    width: 400px;
  }

  .sidebar-content {
    width: 400px;
    height: 100%;
    overflow-y: auto;
    padding: 0;
  }

  .sidebar-header {
    padding: 20px 24px 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
  }

  .sidebar-header .table-title {
    font-size: 16px;
    font-weight: 600;
  }

  .sidebar-header .table-subtitle {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 4px;
  }

  .sidebar-close {
    background: none;
    border: none;
    font-size: 20px;
    cursor: pointer;
    color: var(--text-secondary);
    padding: 4px;
    line-height: 1;
  }

  .sidebar-close:hover {
    color: var(--text);
  }

  .sidebar-fields {
    padding: 16px 24px;
  }

  .sidebar-fields h3 {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
    margin-bottom: 12px;
  }

  .field-list {
    list-style: none;
  }

  .field-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border-radius: var(--radius-sm);
    margin-bottom: 2px;
    font-size: 13px;
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
    transition: background 0.1s;
  }

  .field-item:hover {
    background: var(--bg);
  }

  .field-item .field-name {
    font-weight: 500;
  }

  .field-item .field-comment {
    font-size: 12px;
    color: var(--text-secondary);
    font-family: inherit;
  }

  .field-item .field-key {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    margin-right: 8px;
    flex-shrink: 0;
  }

  .sidebar-rels {
    padding: 16px 24px;
    border-top: 1px solid var(--border);
  }

  .sidebar-rels h3 {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
    margin-bottom: 12px;
  }

  .rel-item {
    padding: 10px 12px;
    background: var(--bg);
    border-radius: var(--radius-sm);
    margin-bottom: 8px;
    font-size: 12px;
  }

  .rel-item .rel-label {
    display: inline-block;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 8px;
    border-radius: 10px;
    background: var(--accent-light);
    color: var(--accent);
    margin-bottom: 6px;
  }

  .rel-item .rel-detail {
    color: var(--text-secondary);
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
  }

  /* Zoom controls */
  .zoom-controls {
    position: absolute;
    bottom: 24px;
    right: 24px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    z-index: 10;
  }

  .zoom-btn {
    width: 36px;
    height: 36px;
    border: 1px solid var(--border);
    background: var(--surface);
    border-radius: var(--radius-sm);
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: var(--shadow);
    transition: all 0.15s;
    color: var(--text);
  }

  .zoom-btn:hover {
    background: var(--bg);
    border-color: var(--accent);
  }

  /* Statement selector */
  .stmt-selector {
    position: absolute;
    top: 16px;
    left: 16px;
    z-index: 10;
    display: flex;
    gap: 6px;
    background: var(--surface);
    padding: 6px;
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    border: 1px solid var(--border);
  }

  .stmt-btn {
    padding: 6px 14px;
    border: none;
    background: transparent;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    color: var(--text-secondary);
    transition: all 0.15s;
  }

  .stmt-btn:hover {
    background: var(--bg);
    color: var(--text);
  }

  .stmt-btn.active {
    background: var(--accent);
    color: white;
  }

  /* Tooltip */
  .tooltip {
    position: absolute;
    padding: 8px 14px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-lg);
    font-size: 13px;
    pointer-events: none;
    z-index: 1000;
    max-width: 280px;
    opacity: 0;
    transition: opacity 0.15s;
  }

  .tooltip.visible {
    opacity: 1;
  }

  /* Legend */
  .legend {
    position: absolute;
    bottom: 24px;
    left: 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 16px;
    box-shadow: var(--shadow);
    font-size: 11px;
    z-index: 10;
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 4px 0;
    color: var(--text-secondary);
  }

  .legend-line {
    width: 24px;
    height: 2px;
    border-radius: 1px;
  }

  /* Empty state */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-secondary);
  }

  .empty-state svg {
    opacity: 0.3;
    margin-bottom: 16px;
  }

  @media (max-width: 768px) {
    .sidebar.open { width: 100%; }
    .header { padding: 12px 16px; }
  }
</style>
</head>
<body>

<div class="header">
  <h1>
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 17v-6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v6"/>
      <path d="M4 21h16"/>
      <path d="M12 15V3"/>
      <path d="M9 6l3-3 3 3"/>
    </svg>
    SQL 关系图
    <span class="badge">RE Diagram</span>
  </h1>
  <div class="header-controls">
    <span class="stmt-indicator" id="stmtInfo">共 <span id="totalStmts">0</span> 段 SQL</span>
    <button class="btn" onclick="resetView()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
      重置视图
    </button>
    <button class="btn" onclick="fitToScreen()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
      适应屏幕
    </button>
  </div>
</div>

<div class="main">
  <div class="diagram-container">
    <div class="stmt-selector" id="stmtSelector"></div>
    <div id="diagram"></div>
    <div class="zoom-controls">
      <button class="zoom-btn" onclick="zoomIn()">+</button>
      <button class="zoom-btn" onclick="zoomOut()">-</button>
      <button class="zoom-btn" onclick="resetView()" style="font-size:12px">&#x22a1;</button>
    </div>
    <div class="legend">
      <div class="legend-item"><div class="legend-line" style="background:var(--accent);border:2px dashed var(--accent);height:0"></div> LEFT JOIN</div>
      <div class="legend-item"><div class="legend-line" style="background:var(--green)"></div> INNER JOIN</div>
      <div class="legend-item"><div class="legend-line" style="background:var(--orange)"></div> FULL JOIN</div>
    </div>
    <div class="tooltip" id="tooltip"></div>
  </div>
  <div class="sidebar" id="sidebar">
    <div class="sidebar-content" id="sidebarContent"></div>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;
let currentStmt = -1; // -1 = all merged
let svg, g, zoom;
let nodes = [], links = [];
let simulation;

// Color palette for databases
const DB_COLORS = {
  "default": { bg: "#f0f4ff", border: "#bfd4ff", text: "#1a40a0" },
};

const DB_PALETTE = [
  { bg: "#eef2ff", border: "#c7d2fe", text: "#3730a3" },
  { bg: "#fdf2f8", border: "#fbc7d4", text: "#9d174d" },
  { bg: "#f0fdf4", border: "#bbf7d0", text: "#166534" },
  { bg: "#fff7ed", border: "#fed7aa", text: "#9a3412" },
  { bg: "#f5f3ff", border: "#ddd6fe", text: "#5b21b6" },
  { bg: "#ecfeff", border: "#a5f3fc", text: "#155e75" },
  { bg: "#fef2f2", border: "#fecaca", text: "#991b1b" },
  { bg: "#faf5ff", border: "#e9d5ff", text: "#701a75" },
];

// Build data - merge all statements when currentStmt == -1
function getMergedData() {
  const allTables = {};
  const allRels = [];
  const addedRels = new Set();

  DATA.forEach(stmt => {
    if (!stmt.tables) return;
    stmt.tables.forEach(t => {
      if (!allTables[t.key]) {
        allTables[t.key] = { ...t, fields: [...t.fields], relationships: [...(t.relationships || [])] };
      } else {
        // Merge fields (deduplicate)
        const existingFields = new Set(allTables[t.key].fields.map(f => f.name));
        t.fields.forEach(f => {
          if (!existingFields.has(f.name)) {
            allTables[t.key].fields.push(f);
            existingFields.add(f.name);
          }
        });
        // Merge relationships
        (t.relationships || []).forEach(r => {
          const rid = r.target_table + ':' + r.source_field + ':' + r.target_field;
          if (!addedRels.has(rid)) {
            allTables[t.key].relationships.push(r);
            addedRels.add(rid);
          }
        });
      }
    });
    // Merge statement-level relationships
    (stmt.relationships || []).forEach(r => {
      const rid = r.source + ':' + r.target + ':' + r.source_field + ':' + r.target_field;
      if (!addedRels.has(rid)) {
        allRels.push(r);
        addedRels.add(rid);
      }
    });
  });

  return { tables: Object.values(allTables), relationships: allRels };
}

function buildGraphData() {
  let stmtData;
  if (currentStmt === -1) {
    stmtData = getMergedData();
  } else {
    stmtData = DATA[currentStmt] || DATA[0];
  }
  if (!stmtData || !stmtData.tables || stmtData.tables.length === 0) return { nodes: [], links: [] };

  const n = [], l = [];

  // Build node groups by database
  const dbGroups = {};
  stmtData.tables.forEach(t => {
    if (!dbGroups[t.db]) dbGroups[t.db] = [];
    dbGroups[t.db].push(t);
  });

  // Assign colors to databases
  const dbColors = {};
  let colorIdx = 0;
  Object.keys(dbGroups).forEach(db => {
    dbColors[db] = DB_PALETTE[colorIdx % DB_PALETTE.length];
    colorIdx++;
  });

  // Create nodes
  stmtData.tables.forEach((t, i) => {
    const fieldCount = (t.fields || []).length;
    let dbColor = dbColors[t.db] || DB_PALETTE[0];
    n.push({
      id: t.key,
      db: t.db,
      table: t.table,
      alias: t.alias || '',
      fields: t.fields || [],
      relationships: t.relationships || [],
      fieldCount: fieldCount,
      dbColor: dbColor,
      x: 200 + Math.random() * 600,
      y: 150 + Math.random() * 400,
    });
  });

  // Build links from relationships
  const addedLinks = new Set();
  (stmtData.relationships || []).forEach(r => {
    const linkId = [r.source, r.target].sort().join('->');
    if (!addedLinks.has(linkId)) {
      addedLinks.add(linkId);
      const isLeft = r.join_type === 'LEFT JOIN';
      l.push({
        source: r.source,
        target: r.target,
        sourceField: r.source_field,
        targetField: r.target_field,
        joinType: r.join_type,
        stroke: isLeft ? 'var(--accent)' : r.join_type === 'FULL JOIN' ? 'var(--orange)' : 'var(--green)',
        strokeDash: isLeft ? '8,4' : 'none',
      });
    }
  });

  return { nodes: n, links: l };
}

// Initialize
function init() {
  const container = document.getElementById('diagram');
  const rect = container.getBoundingClientRect();
  const width = rect.width || 1200;
  const height = rect.height || 800;

  svg = d3.select('#diagram')
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .style('cursor', 'grab');

  g = svg.append('g');

  zoom = d3.zoom()
    .scaleExtent([0.1, 4])
    .on('zoom', (event) => {
      g.attr('transform', event.transform);
    });

  svg.call(zoom);

  // Resize handler
  window.addEventListener('resize', () => {
    const r = container.getBoundingClientRect();
    svg.attr('width', r.width).attr('height', r.height);
  });

  // Build stmt selector
  buildStmtSelector();
  render();
}

function buildStmtSelector() {
  const container = document.getElementById('stmtSelector');
  container.innerHTML = '';
  if (DATA.length <= 1) {
    container.style.display = 'none';
    document.getElementById('totalStmts').textContent = '1';
    return;
  }
  document.getElementById('totalStmts').textContent = DATA.length;

  // "All merged" button
  const allBtn = document.createElement('button');
  allBtn.className = 'stmt-btn' + (currentStmt === -1 ? ' active' : '');
  allBtn.textContent = '全部合并';
  allBtn.dataset.stmtIdx = '-1';
  allBtn.onclick = () => selectStmt(-1);
  container.appendChild(allBtn);

  // Individual SQL statement buttons
  DATA.forEach((d, i) => {
    const btn = document.createElement('button');
    btn.className = 'stmt-btn' + (i === currentStmt ? ' active' : '');
    btn.textContent = 'SQL ' + (i + 1);
    btn.dataset.stmtIdx = '' + i;
    btn.onclick = () => selectStmt(i);
    container.appendChild(btn);
  });
}

function selectStmt(idx) {
  currentStmt = idx;
  document.querySelectorAll('.stmt-btn').forEach((b) => {
    const btnIdx = parseInt(b.dataset.stmtIdx, 10);
    b.className = 'stmt-btn' + (btnIdx === idx ? ' active' : '');
  });
  closeSidebar();
  render();
}

function render() {
  const { nodes: newNodes, links: newLinks } = buildGraphData();
  nodes = newNodes;
  links = newLinks;

  g.selectAll('*').remove();

  if (nodes.length === 0) {
    g.append('text')
      .attr('x', 400).attr('y', 300)
      .attr('text-anchor', 'middle')
      .attr('fill', '#6b7094')
      .style('font-size', '16px')
      .text('未解析到任何表结构');
    return;
  }

  // Arrow markers
  const defs = g.append('defs');
  defs.append('marker')
    .attr('id', 'arrowhead')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 28)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-4L8,0L0,4')
    .attr('fill', '#b0b7d1');

  // Links (edges)
  const linkGroup = g.append('g').attr('class', 'links');

  const link = linkGroup.selectAll('g.link')
    .data(links)
    .join('g')
    .attr('class', 'link');

  link.append('path')
    .attr('stroke', d => d.stroke)
    .attr('stroke-width', 2)
    .attr('stroke-dasharray', d => d.strokeDash)
    .attr('fill', 'none')
    .attr('marker-end', 'url(#arrowhead)')
    .style('cursor', 'pointer');

  link.append('title')
    .text(d => d.joinType + '\n' + d.sourceField + ' -> ' + d.targetField);

  // Link labels
  link.append('text')
    .attr('class', 'link-label')
    .attr('text-anchor', 'middle')
    .attr('dy', -6)
    .attr('fill', d => d.stroke)
    .style('font-size', '10px')
    .style('font-weight', '500')
    .style('pointer-events', 'none')
    .style('opacity', 0.8)
    .text(d => {
      const sf = d.sourceField.length > 12 ? d.sourceField.slice(0,10)+'..' : d.sourceField;
      return sf + ' -> ' + d.targetField;
    });

  // Database group backgrounds
  const dbGroupMap = {};
  nodes.forEach(n => {
    if (!dbGroupMap[n.db]) dbGroupMap[n.db] = [];
    dbGroupMap[n.db].push(n);
  });

  const dbGroup = g.append('g').attr('class', 'db-groups');

  // Calculate node dimensions
  const nodeW = 200;
  const headerH = 36;
  const fieldH = 24;
  const padding = 40;

  // Simulation
  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(280))
    .force('charge', d3.forceManyBody().strength(-600))
    .force('center', d3.forceCenter(600, 400))
    .force('collision', d3.forceCollide().radius(130))
    .on('end', () => {
      updatePositions();
      drawDbBackgrounds();
      fitToScreen();
    });

  // Node groups
  const nodeGroup = g.append('g').attr('class', 'nodes');

  const node = nodeGroup.selectAll('g.node')
    .data(nodes)
    .join('g')
    .attr('class', 'node')
    .style('cursor', 'pointer');

  // Table cards
  const card = node.append('g');

  // Card background
  const nodeHeight = d => headerH + fieldH * Math.min(d.fields.length + 1, 8) + 12;

  card.append('rect')
    .attr('class', 'card-bg')
    .attr('x', -nodeW/2)
    .attr('y', -20)
    .attr('width', nodeW)
    .attr('height', d => nodeHeight(d))
    .attr('rx', 10)
    .attr('ry', 10)
    .attr('fill', 'var(--surface)')
    .attr('stroke', d => d.dbColor.border)
    .attr('stroke-width', 1.5)
    .attr('filter', 'drop-shadow(0 1px 3px rgba(0,0,0,0.06))');

  // Table header
  card.append('rect')
    .attr('class', 'card-header-bg')
    .attr('x', -nodeW/2)
    .attr('y', -20)
    .attr('width', nodeW)
    .attr('height', headerH)
    .attr('rx', 10)
    .attr('ry', 10)
    .attr('fill', d => d.dbColor.bg);

  // Header bottom rounded corners fix
  card.append('rect')
    .attr('x', -nodeW/2)
    .attr('y', -20 + headerH - 6)
    .attr('width', nodeW)
    .attr('height', 6)
    .attr('fill', d => d.dbColor.bg);

  // DB badge
  card.append('text')
    .attr('class', 'db-badge')
    .attr('x', -nodeW/2 + 12)
    .attr('y', -20 + headerH/2 + 1)
    .attr('fill', d => d.dbColor.text)
    .style('font-size', '9px')
    .style('font-weight', '600')
    .style('text-transform', 'uppercase')
    .style('letter-spacing', '0.3px')
    .style('opacity', 0.7)
    .text(d => d.db);

  // Table name
  card.append('text')
    .attr('class', 'table-name')
    .attr('text-anchor', 'middle')
    .attr('y', -20 + headerH/2 + 1)
    .attr('fill', 'var(--text)')
    .style('font-size', '13px')
    .style('font-weight', '600')
    .style('letter-spacing', '-0.2px')
    .text(d => d.table);

  // Field count badge
  card.append('text')
    .attr('x', nodeW/2 - 12)
    .attr('y', -20 + headerH/2 + 1)
    .attr('text-anchor', 'end')
    .attr('fill', 'var(--text-secondary)')
    .style('font-size', '10px')
    .style('font-weight', '500')
    .text(d => '' + d.fields.length);

  // Fields
  const fieldsGroup = card.append('g');

  fieldsGroup.selectAll('g.field-row')
    .data(d => {
      const displayFields = d.fields.slice(0, 8);
      const remaining = d.fields.length - 8;
      return displayFields.map(f => ({ ...f, tableKey: d.id, totalFields: d.fields.length, remaining }));
    })
    .join('g')
    .attr('class', 'field-row')
    .attr('transform', (d, i) => 'translate(0, ' + (-20 + headerH + 6 + i * fieldH) + ')')
    .each(function(d) {
      const row = d3.select(this);
      row.append('circle')
        .attr('r', 3)
        .attr('cx', -nodeW/2 + 14)
        .attr('cy', 0)
        .attr('fill', 'var(--accent)')
        .attr('opacity', 0.5);
      row.append('text')
        .attr('x', -nodeW/2 + 24)
        .attr('y', 4)
        .attr('fill', 'var(--text)')
        .style('font-size', '11px')
        .style('font-family', '"SF Mono", "Menlo", "Consolas", monospace')
        .text(d.name.length > 22 ? d.name.slice(0, 20) + '...' : d.name);
    });

  // More fields indicator
  fieldsGroup.selectAll('g.more-fields')
    .data(d => d.fields.length > 8 ? [d] : [])
    .join('g')
    .attr('transform', d => 'translate(0, ' + (-20 + headerH + 6 + 8 * fieldH) + ')')
    .each(function() {
      d3.select(this).append('text')
        .attr('x', 0)
        .attr('y', 4)
        .attr('text-anchor', 'middle')
        .attr('fill', 'var(--text-secondary)')
        .style('font-size', '10px')
        .text(d => '+' + (d.fields.length - 8) + ' more fields');
    });

  // No fields indicator
  fieldsGroup.selectAll('g.no-fields')
    .data(d => d.fields.length === 0 ? [d] : [])
    .join('g')
    .attr('transform', d => 'translate(0, ' + (-20 + headerH + 10) + ')')
    .each(function() {
      d3.select(this).append('text')
        .attr('x', 0)
        .attr('y', 4)
        .attr('text-anchor', 'middle')
        .attr('fill', 'var(--text-secondary)')
        .style('font-size', '11px')
        .style('font-style', 'italic')
        .text('no fields extracted');
    });

  // Click handler
  node.on('click', (event, d) => {
    event.stopPropagation();
    showTableDetail(d);
  });

  // Hover tooltip
  node.on('mouseenter', (event, d) => {
    const tooltip = document.getElementById('tooltip');
    tooltip.textContent = d.db + '::' + d.table + ' | ' + d.fields.length + ' fields';
    tooltip.className = 'tooltip visible';
  });

  node.on('mousemove', (event) => {
    const tooltip = document.getElementById('tooltip');
    tooltip.style.left = (event.offsetX + 12) + 'px';
    tooltip.style.top = (event.offsetY - 10) + 'px';
  });

  node.on('mouseleave', () => {
    document.getElementById('tooltip').className = 'tooltip';
  });

  // Drag behavior
  node.call(d3.drag()
    .on('start', (event, d) => {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    })
    .on('drag', (event, d) => {
      d.fx = event.x;
      d.fy = event.y;
    })
    .on('end', (event, d) => {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }));

  // Click background to close sidebar
  svg.on('click', () => closeSidebar());

  simulation.nodes(nodes);
  simulation.force('link').links(links);
}

function updatePositions() {
  // Update node positions
  g.selectAll('g.node')
    .attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');

  // Update link positions
  g.selectAll('g.link path')
    .attr('d', d => {
      const dx = d.target.x - d.source.x;
      const dy = d.target.y - d.source.y;
      const dr = Math.sqrt(dx * dx + dy * dy);
      const midX = (d.source.x + d.target.x) / 2;
      const midY = (d.source.y + d.target.y) / 2;
      // Slight curve for readability
      const curvature = 0.1;
      const cx = midX - dy * curvature;
      const cy = midY + dx * curvature;
      return 'M' + d.source.x + ',' + d.source.y + 'Q' + cx + ',' + cy + ' ' + d.target.x + ',' + d.target.y;
    });

  // Update link labels
  g.selectAll('g.link text.link-label')
    .attr('x', d => (d.source.x + d.target.x) / 2)
    .attr('y', d => (d.source.y + d.target.y) / 2 - 8);
}

function drawDbBackgrounds() {
  // Calculate bounding boxes for each database group
  const dbBounds = {};
  g.selectAll('g.node').each(function(d) {
    const bbox = this.getBBox();
    if (!dbBounds[d.db]) {
      dbBounds[d.db] = { minX: bbox.x, minY: bbox.y, maxX: bbox.x + bbox.width, maxY: bbox.y + bbox.height };
    } else {
      dbBounds[d.db].minX = Math.min(dbBounds[d.db].minX, bbox.x);
      dbBounds[d.db].minY = Math.min(dbBounds[d.db].minY, bbox.y);
      dbBounds[d.db].maxX = Math.max(dbBounds[d.db].maxX, bbox.x + bbox.width);
      dbBounds[d.db].maxY = Math.max(dbBounds[d.db].maxY, bbox.y + bbox.height);
    }
  });

  // Remove old backgrounds
  dbGroup.selectAll('*').remove();

  Object.entries(dbBounds).forEach(([db, bounds]) => {
    const color = nodes.find(n => n.db === db)?.dbColor || DB_PALETTE[0];
    const pad = 24;
    dbGroup.append('rect')
      .attr('x', bounds.minX - pad)
      .attr('y', bounds.minY - pad - 24)
      .attr('width', bounds.maxX - bounds.minX + pad * 2)
      .attr('height', bounds.maxY - bounds.minY + pad * 2 + 24)
      .attr('rx', 14)
      .attr('ry', 14)
      .attr('fill', color.bg)
      .attr('opacity', 0.4)
      .attr('stroke', color.border)
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '4,4');

    // DB label
    dbGroup.append('text')
      .attr('x', bounds.minX - pad + 14)
      .attr('y', bounds.minY - pad - 4)
      .attr('fill', color.text)
      .style('font-size', '12px')
      .style('font-weight', '600')
      .style('text-transform', 'uppercase')
      .style('letter-spacing', '0.5px')
      .style('opacity', 0.7)
      .text(db);
  });
}

// Simulation tick handler
function tickHandler() {
  updatePositions();
}

// Zoom controls
function zoomIn() {
  svg.transition().duration(300).call(zoom.scaleBy, 1.3);
}

function zoomOut() {
  svg.transition().duration(300).call(zoom.scaleBy, 0.7);
}

function resetView() {
  svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
}

function fitToScreen() {
  const bounds = g.node()?.getBBox();
  if (!bounds) return;
  const container = document.getElementById('diagram');
  const cw = container.clientWidth;
  const ch = container.clientHeight;
  const scale = Math.min(cw / bounds.width, ch / bounds.height, 1.5) * 0.85;
  const tx = (cw - bounds.width * scale) / 2 - bounds.x * scale;
  const ty = (ch - bounds.height * scale) / 2 - bounds.y * scale;
  svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

// Sidebar - Table detail
function showTableDetail(d) {
  const sidebar = document.getElementById('sidebar');
  const content = document.getElementById('sidebarContent');
  sidebar.className = 'sidebar open';

  let fieldsHtml = '';
  if (d.fields.length === 0) {
    fieldsHtml = '<div style="color:var(--text-secondary);font-style:italic;font-size:13px;padding:12px">未提取到字段信息</div>';
  } else {
    d.fields.forEach(f => {
      fieldsHtml += '<div class="field-item">' +
        '<span><span class="field-key" style="background:var(--accent)"></span><span class="field-name">' + f.name + '</span></span>' +
        '<span class="field-comment">' + (f.comment || '-') + '</span>' +
        '</div>';
    });
  }

  let relsHtml = '';
  const allRels = [];
  if (d.relationships) {
    d.relationships.forEach(r => {
      const target = nodes.find(n => n.id === r.target_table);
      allRels.push({
        targetName: target ? target.db + '::' + target.table : r.target_table,
        sourceField: r.source_field,
        targetField: r.target_field,
        joinType: r.join_type,
      });
    });
  }
  // Also find reverse relationships
  links.forEach(l => {
    if (l.target === d.id) {
      const source = nodes.find(n => n.id === l.source);
      if (!allRels.find(r => r.sourceField === l.targetField && r.targetField === l.sourceField)) {
        allRels.push({
          targetName: source ? source.db + '::' + source.table : l.source,
          sourceField: l.targetField,
          targetField: l.sourceField,
          joinType: l.joinType,
        });
      }
    }
  });

  if (allRels.length === 0) {
    relsHtml = '<div style="color:var(--text-secondary);font-style:italic;font-size:13px;padding:12px">无关联关系</div>';
  } else {
    allRels.forEach(r => {
      relsHtml += '<div class="rel-item">' +
        '<div class="rel-label">' + r.joinType + '</div>' +
        '<div class="rel-detail">' + r.sourceField + ' -> ' + r.targetField + '</div>' +
        '<div style="font-size:11px;color:var(--text-secondary);margin-top:4px">' + r.targetName + '</div>' +
        '</div>';
    });
  }

  content.innerHTML =
    '<div class="sidebar-header">' +
      '<div>' +
        '<div class="table-title">' + d.table + '</div>' +
        '<div class="table-subtitle">' + d.db + '<span style="margin:0 8px">·</span>' + d.fields.length + ' 个字段</div>' +
      '</div>' +
      '<button class="sidebar-close" onclick="closeSidebar()">X</button>' +
    '</div>' +
    '<div class="sidebar-fields">' +
      '<h3>字段列表</h3>' +
      '<div class="field-list">' + fieldsHtml + '</div>' +
    '</div>' +
    '<div class="sidebar-rels">' +
      '<h3>关联关系</h3>' +
      relsHtml +
    '</div>';
}

function closeSidebar() {
  document.getElementById('sidebar').className = 'sidebar';
}

// Init on load
document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python sql_to_re.py <sql_file> [output_html]")
        sys.exit(1)

    sql_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else sql_path.replace('.sql', '_re.html')

    if not Path(sql_path).exists():
        print(f"[!] File not found: {sql_path}")
        sys.exit(1)

    parser = SQLParser()
    generator = REDiagramGenerator()

    print(f"[*] Parsing: {sql_path}")
    results = parser.parse_file(sql_path)

    if not results:
        print("[!] No SQL statements parsed.")
        sys.exit(1)

    print(f"[*] Parsed {len(results)} SQL statement(s)")
    for i, r in enumerate(results):
        print(f"   [{i+1}] {len(r['tables'])} tables, {len(r['relationships'])} relationships")

    generator.generate(results, output_path)
    print(f"\n[OK] Done! Open {output_path} in browser to view.")


if __name__ == "__main__":
    main()
