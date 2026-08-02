"""
Query plan fingerprinting, AST hashing and plan/result diffing.

The goal is to compare execution plans of *semantically* identical queries
that may differ in non-essential formatting (JSON key order, whitespace,
cosmetic alias differences) without producing false version differences,
while still detecting real changes to JOINs, filters, aggregations or
index access.

No sensitive parameter *values* are ever stored -- only their declared
types and null-ness. The EXPLAIN QUERY PLAN output is parsed into a
structured, AST-node-keyed fingerprint so the frontend can localise
changes to a specific JOIN, filter, aggregation or index access rather
than to a line number in SQL text.
"""
import hashlib
import json
import re
from copy import deepcopy


# ---------------------------------------------------------------------------
# AST canonicalisation + hashing
# ---------------------------------------------------------------------------
# Keys that do not affect SQL semantics: UI positions, cosmetic labels and
# client-generated timestamps. These are stripped before hashing so that
# moving a node on the canvas does not create a new plan version.
AST_NONSEMANTIC_KEYS = {
    'position', 'x', 'y', 'label', 'help', 'options', 'selected',
    'expanded', 'active', 'dragging',
}

# Pagination defaults that should not count as a semantic difference when
# they match the generator's own defaults.
DEFAULT_LIMIT = 100
DEFAULT_OFFSET = 0


def canonical_ast(ast):
    """
    Return a deterministic, semantically-normalised copy of the AST.

    - Strips UI-only keys (positions, labels).
    - Removes default limit/offset so cosmetic changes do not hash differently.
    - Sorts object keys and list order where order is semantically irrelevant
      (selected fields / aggregations are order-sensitive in SQL, so their
      order is preserved; but the CTE/params maps are sorted).
    """
    if isinstance(ast, dict):
        out = {}
        for key in sorted(ast.keys()):
            if key in AST_NONSEMANTIC_KEYS:
                continue
            value = ast[key]
            if key == 'limit' and value == DEFAULT_LIMIT:
                continue
            if key == 'offset' and value in (None, DEFAULT_OFFSET):
                continue
            if key == 'alias' and not value:
                continue
            out[key] = canonical_ast(value)
        return out
    if isinstance(ast, list):
        return [canonical_ast(item) for item in ast]
    return ast


def hash_ast(ast):
    """Stable SHA-256 hash of a semantically-canonical AST."""
    canonical = canonical_ast(ast)
    blob = json.dumps(
        canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=False
    )
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def parameter_type_summary(params):
    """
    Produce a non-sensitive fingerprint of the parameter *types* supplied
    at execution time. Only parameter names, declared/inferred types, and
    whether a value was NULL are recorded -- never the value itself.

    Accepts either a dict of resolved values or a list of parameter
    declarations.
    """
    summary = []
    if isinstance(params, dict):
        for name in sorted(params.keys()):
            value = params[name]
            summary.append({
                'name': name,
                'type': _infer_type(value),
                'isNull': value is None,
            })
    elif isinstance(params, list):
        for decl in sorted(params or [], key=lambda p: p.get('name', '')):
            summary.append({
                'name': decl.get('name'),
                'type': decl.get('type', 'unknown'),
                'isNull': decl.get('default') is None and not decl.get('required'),
            })
    return summary


def _infer_type(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        if not value:
            return 'list'
        return f'{_infer_type(value[0])}_list'
    return type(value).__name__


# ---------------------------------------------------------------------------
# EXPLAIN QUERY PLAN parsing
# ---------------------------------------------------------------------------
# SQLite EXPLAIN QUERY PLAN rows are (id, parent, notused, detail).
# We map each scan/search to a table instance in the AST via the physical
# table name, then build a stable fingerprint keyed by (alias, operation).

_SCAN_RE = re.compile(
    r'^(SCAN|SEARCH)\s+(?:TABLE\s+)?([A-Za-z_][A-Za-z0-9_]*)'
    r'(?:\s+AS\s+([A-Za-z_][A-Za-z0-9_]*))?'
    r'(?:\s+USING\s+(?:COVERING\s+)?INDEX\s+([A-Za-z_][A-Za-z0-9_]*))?',
    re.IGNORECASE,
)
_TEMP_BTREE_RE = re.compile(r'USING\s+TEMP\s+BTREE', re.IGNORECASE)
_LIST_SUBQUERY_RE = re.compile(r'LIST\s+SUBQUERY', re.IGNORECASE)
_ROWS_RE = re.compile(r'~?(\d+)\s+rows?', re.IGNORECASE)


def parse_plan_rows(plan_rows):
    """
    Parse raw SQLite EXPLAIN QUERY PLAN rows into structured access nodes.

    Each node describes one table access with its operation, index and
    estimated rows. Composite operations (temp b-trees for sorts/guides,
    list subqueries) are captured as structural markers.
    """
    nodes = []
    for row in plan_rows:
        if isinstance(row, (tuple, list)):
            detail = row[3] if len(row) > 3 else ''
            node_id = row[0]
            parent_id = row[1]
        else:
            detail = row.get('detail', '')
            node_id = row.get('id')
            parent_id = row.get('parent')

        node = {
            'id': node_id,
            'parentId': parent_id if parent_id not in (None, 0) else None,
            'detail': detail,
            'operation': None,
            'tableName': None,
            'alias': None,
            'indexName': None,
            'estimatedRows': None,
            'isFullScan': False,
            'isCovering': False,
            'tempBTree': bool(_TEMP_BTREE_RE.search(detail)),
            'listSubquery': bool(_LIST_SUBQUERY_RE.search(detail)),
        }

        match = _SCAN_RE.search(detail)
        if match:
            op, table, alias, index = match.groups()
            node['operation'] = op.upper()
            node['tableName'] = table
            node['alias'] = alias or table
            node['indexName'] = index
            node['isFullScan'] = op.upper() == 'SCAN'
            node['isCovering'] = (
                'COVERING INDEX' in detail.upper()
            )

        rows_match = _ROWS_RE.search(detail)
        if rows_match:
            node['estimatedRows'] = int(rows_match.group(1))

        nodes.append(node)
    return nodes


def build_plan_fingerprint(plan_nodes, table_instances):
    """
    Build a canonical, alias-keyed fingerprint of a plan.

    ``table_instances`` maps alias -> {tableName, tableId} so a physical
    table accessed via a self-join alias maps to the right AST table
    instance. The fingerprint is a sorted list of access descriptors;
    volatile row estimates are kept separately (they affect performance
    comparisons but not structural equality).
    """
    accesses = []
    for node in plan_nodes:
        if not node['operation']:
            continue
        alias = node['alias'] or node['tableName']
        instance = table_instances.get(alias, {})
        accesses.append({
            'tableId': instance.get('tableId', alias),
            'tableName': node['tableName'],
            'alias': alias,
            'operation': node['operation'],
            'indexName': node['indexName'],
            'isCovering': node['isCovering'],
            'tempBTree': node['tempBTree'],
            'listSubquery': node['listSubquery'],
        })

    # Sort deterministically so equivalent plans in different row order
    # hash identically.
    accesses.sort(key=lambda a: (
        a['tableId'], a['operation'], a['indexName'] or '',
    ))

    structural = json.dumps(
        accesses, sort_keys=True, separators=(',', ':')
    )
    return hashlib.sha256(structural.encode('utf-8')).hexdigest()


def table_instances_from_ast(ast):
    """Build an alias -> table metadata map from a query AST."""
    result = {}
    for table in ast.get('tables', []) or []:
        alias = table.get('alias') or table['id']
        result[alias] = {
            'tableId': table['id'],
            'tableName': table['tableName'],
            'alias': alias,
        }
    return result


# ---------------------------------------------------------------------------
# Plan/result diff engine
# ---------------------------------------------------------------------------
def diff_plans(plan_a, plan_b, ast_a, ast_b):
    """
    Compare two parsed plans and return a change set localised to AST
    nodes (table instance id, join id, or "aggregation"/"sort").

    The diff is structural (operations/indexes) plus performance
    (estimated/actual row counts). It never refers to SQL line numbers.
    """
    instances_a = table_instances_from_ast(ast_a)
    instances_b = table_instances_from_ast(ast_b)

    accesses_a = _index_accesses(plan_a, instances_a)
    accesses_b = _index_accesses(plan_b, instances_b)

    changes = []
    all_keys = set(accesses_a) | set(accesses_b)
    for key in sorted(all_keys):
        a = accesses_a.get(key)
        b = accesses_b.get(key)
        if a and not b:
            changes.append(_change(
                kind='access_removed',
                tableId=a['tableId'],
                label=f'Table access removed: {a["alias"]}',
                before=a, after=None,
            ))
        elif b and not a:
            changes.append(_change(
                kind='access_added',
                tableId=b['tableId'],
                label=f'Table access added: {b["alias"]}',
                before=None, after=b,
            ))
        else:
            if a['operation'] != b['operation']:
                changes.append(_change(
                    kind='operation_changed',
                    tableId=b['tableId'],
                    label=(
                        f'{b["alias"]}: {a["operation"]} → '
                        f'{b["operation"]}'
                    ),
                    before=a['operation'], after=b['operation'],
                ))
            if a['indexName'] != b['indexName']:
                changes.append(_change(
                    kind='index_changed',
                    tableId=b['tableId'],
                    label=(
                        f'{b["alias"]} index: '
                        f'{a["indexName"] or "—"} → '
                        f'{b["indexName"] or "—"}'
                    ),
                    before=a['indexName'], after=b['indexName'],
                ))
            if a['isCovering'] != b['isCovering']:
                changes.append(_change(
                    kind='covering_changed',
                    tableId=b['tableId'],
                    label=f'{b["alias"]} covering index changed',
                    before=a['isCovering'], after=b['isCovering'],
                ))
            if (a['estimatedRows'] or 0) != (b['estimatedRows'] or 0):
                changes.append(_change(
                    kind='row_estimate_changed',
                    tableId=b['tableId'],
                    label=(
                        f'{b["alias"]} estimate: '
                        f'~{a["estimatedRows"] or "?"} → '
                        f'~{b["estimatedRows"] or "?"}'
                    ),
                    before=a['estimatedRows'],
                    after=b['estimatedRows'],
                ))

    # Structural: temp b-trees (sorts, GROUP BY) and list subqueries
    for kind, flag_a, flag_b, label in (
        ('temp_btree_changed',
         any(n['tempBTree'] for n in plan_a),
         any(n['tempBTree'] for n in plan_b),
         'Temporary B-tree (sort/group) usage changed'),
        ('list_subquery_changed',
         any(n['listSubquery'] for n in plan_a),
         any(n['listSubquery'] for n in plan_b),
         'List subquery usage changed'),
    ):
        if flag_a != flag_b:
            changes.append(_change(
                kind=kind,
                label=label,
                before=flag_a, after=flag_b,
            ))

    # Localise AST-level changes by diffing the ASTs themselves.
    changes.extend(_diff_ast_structure(ast_a, ast_b))

    return changes


def _index_accesses(plan_nodes, instances):
    out = {}
    for node in plan_nodes:
        if not node['operation']:
            continue
        alias = node['alias'] or node['tableName']
        instance = instances.get(alias, {})
        out[instance.get('tableId', alias)] = {
            'tableId': instance.get('tableId', alias),
            'alias': alias,
            'operation': node['operation'],
            'indexName': node['indexName'],
            'isCovering': node['isCovering'],
            'estimatedRows': node['estimatedRows'],
        }
    return out


def _change(kind, label, before=None, after=None, tableId=None, joinId=None):
    return {
        'kind': kind,
        'label': label,
        'tableId': tableId,
        'joinId': joinId,
        'before': before,
        'after': after,
    }


def _diff_ast_structure(ast_a, ast_b):
    """Localise non-cosmetic AST differences to specific node types."""
    changes = []

    # JOIN changes
    joins_a = {j['id']: j for j in (ast_a.get('joins') or [])}
    joins_b = {j['id']: j for j in (ast_b.get('joins') or [])}
    for jid in set(joins_a) - set(joins_b):
        changes.append(_change(
            kind='join_removed', joinId=jid,
            label=f'JOIN {jid} removed',
        ))
    for jid in set(joins_b) - set(joins_a):
        changes.append(_change(
            kind='join_added', joinId=jid,
            label=f'JOIN {jid} added',
        ))
    for jid in set(joins_a) & set(joins_b):
        ja, jb = joins_a[jid], joins_b[jid]
        if ja.get('type') != jb.get('type'):
            changes.append(_change(
                kind='join_type_changed', joinId=jid,
                label=f'JOIN {jid}: {ja.get("type")} → {jb.get("type")}',
                before=ja.get('type'), after=jb.get('type'),
            ))
        if (ja.get('leftColumn'), ja.get('rightColumn')) != \
           (jb.get('leftColumn'), jb.get('rightColumn')):
            changes.append(_change(
                kind='join_condition_changed', joinId=jid,
                label=f'JOIN {jid} condition changed',
            ))

    # WHERE / HAVING filter changes
    for clause, label in (('where', 'WHERE'), ('having', 'HAVING')):
        ha = _hash_node(ast_a.get(clause))
        hb = _hash_node(ast_b.get(clause))
        if ha != hb:
            changes.append(_change(
                kind=f'{clause}_changed',
                label=f'{label} filter changed',
            ))

    # Aggregation changes
    agg_a = _hash_node(ast_a.get('aggregations'))
    agg_b = _hash_node(ast_b.get('aggregations'))
    if agg_a != agg_b:
        changes.append(_change(
            kind='aggregation_changed',
            label='Aggregation/GROUP BY changed',
        ))

    # Selected fields
    sel_a = _hash_node(ast_a.get('selectedFields'))
    sel_b = _hash_node(ast_b.get('selectedFields'))
    if sel_a != sel_b:
        changes.append(_change(
            kind='select_changed',
            label='Selected columns changed',
        ))

    return changes


def _hash_node(node):
    if node is None:
        return None
    canonical = canonical_ast(node)
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()


def summarize_result_stats(rows):
    """Produce a compact, non-sensitive result summary."""
    if not rows:
        return {'rowCount': 0, 'columnCount': 0}
    return {
        'rowCount': len(rows),
        'columnCount': len(rows[0]),
    }
