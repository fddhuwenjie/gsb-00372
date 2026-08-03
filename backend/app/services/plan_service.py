"""
Query execution plan capture, normalization, and structural diffing.

Key design:
- AST hash is canonical (semantic): ignores ephemeral UI node IDs, positions,
  whitespace, and parameter VALUES. Two queries with identical semantics produce
  the same hash regardless of formatting or ID reassignment.
- Parameter type summary records only parameter names and types, never values.
- Plan operations are normalized from SQLite EXPLAIN QUERY PLAN output into
  structured records, each mapped back to AST node IDs (table, join, filter,
  aggregation). No SQL line numbers are used.
- Diff produces a change set keyed by semantic AST node keys, so non-semantic
  changes (formatting, ID reassignment) produce an empty diff while real changes
  (JOIN type, filter removal, index usage) produce a stable change set.
"""
import hashlib
import json
import re
from copy import deepcopy


# ---------------------------------------------------------------------------
# Canonical AST hashing
# ---------------------------------------------------------------------------

def _canonicalize(obj):
    """Recursively strip non-semantic fields and produce a deterministic form.

    Strips:
    - Ephemeral UI node IDs, positions, descriptions, labels
    - Literal comparison VALUES (these are runtime data, not structure)
    But preserves:
    - Table/column references, operators, join types, $param references
    """
    if isinstance(obj, dict):
        result = {}
        for key in sorted(obj.keys()):
            if key in ('id', 'position', 'description', 'label'):
                continue
            if key == 'value':
                v = obj[key]
                if isinstance(v, dict) and '$param' in v:
                    result[key] = {'$param': v['$param']}
                elif isinstance(v, list) and v and isinstance(v[0], dict) and '$param' in v[0]:
                    result[key] = [{'$param': item['$param']} for item in v]
                else:
                    result[key] = '<literal>'
                continue
            if key == 'paramRef':
                result[key] = obj[key]
                continue
            result[key] = _canonicalize(obj[key])
        return result
    if isinstance(obj, list):
        if not obj:
            return []
        return [_canonicalize(item) for item in obj]
    return obj


def compute_ast_hash(query_structure):
    """Return a SHA-256 hex digest of the canonical semantic AST."""
    canonical = _canonicalize(query_structure)
    serialized = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# Parameter type summary (never stores values)
# ---------------------------------------------------------------------------

def compute_param_type_summary(parameters):
    """Return {param_name: param_type} — types only, no values."""
    summary = {}
    for param in parameters or []:
        name = param.get('name')
        ptype = param.get('type')
        if name and ptype:
            summary[name] = ptype
    return summary


# ---------------------------------------------------------------------------
# EXPLAIN QUERY PLAN parsing and normalization
# ---------------------------------------------------------------------------

_SCAN_PATTERNS = [
    (re.compile(r'\bSCAN\s+(?:TABLE\s+)?(\S+)(?:\s+AS\s+(\S+))?', re.IGNORECASE), 'SCAN'),
    (re.compile(r'\bSEARCH\s+(?:TABLE\s+)?(\S+)(?:\s+AS\s+(\S+))?', re.IGNORECASE), 'SEARCH'),
]

_INDEX_PATTERN = re.compile(
    r'USING\s+(?:COVERING\s+)?(?:INDEX\s+)?(\S+)', re.IGNORECASE
)
_PK_LOOKUP_PATTERN = re.compile(r'USING\s+INTEGER\s+PRIMARY\s+KEY', re.IGNORECASE)

_COMPOUND_PATTERNS = [
    (re.compile(r'USE\s+TEMP\s+B-TREE\s+FOR\s+(GROUP\s+BY|ORDER\s+BY)', re.IGNORECASE), 'TEMP_BTREE'),
    (re.compile(r'USING\s+TEMP\s+B-TREE', re.IGNORECASE), 'TEMP_BTREE'),
    (re.compile(r'USING\s+INDEX', re.IGNORECASE), 'INDEX_SCAN'),
    (re.compile(r'CORRELATED\s+SCALAR', re.IGNORECASE), 'CORRELATED_SCALAR'),
    (re.compile(r'LIST\s+OF\s+SUBQUERIES', re.IGNORECASE), 'SUBQUERY_LIST'),
]


def _strip_quotes(name):
    if not name:
        return name
    name = name.strip()
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1].replace('""', '"')
    if name.startswith('`') and name.endswith('`'):
        name = name[1:-1]
    return name


def _build_alias_map(query_structure):
    """Map alias -> {tableId, tableName} and table name -> tableId."""
    alias_map = {}
    for table in query_structure.get('tables', []):
        alias = table.get('alias', '')
        tid = table.get('id')
        tname = table.get('tableName', '')
        alias_map[alias] = {'tableId': tid, 'tableName': tname}
        alias_map[tname] = {'tableId': tid, 'tableName': tname}
        alias_map[tname.lower()] = {'tableId': tid, 'tableName': tname}
        alias_map[alias.lower()] = {'tableId': tid, 'tableName': tname}
    return alias_map


def _find_join_id(query_structure, left_id, right_id):
    for join in query_structure.get('joins', []):
        l = join.get('leftTableId')
        r = join.get('rightTableId')
        if (l == left_id and r == right_id) or (l == right_id and r == left_id):
            return join.get('id')
    return None


def _find_filter_ids(query_structure, table_id):
    """Return semantic keys for WHERE/HAVING conditions on a table."""
    filter_keys = []

    def walk(node, clause):
        if not node:
            return
        if 'children' in node:
            for child in node.get('children', []):
                walk(child, clause)
        elif 'tableId' in node and node.get('tableId') == table_id:
            col = node.get('columnName', '')
            cmp = node.get('cmp', '')
            filter_keys.append(f'filter:{table_id}.{col}:{cmp}:{clause}')

    walk(query_structure.get('where'), 'where')
    walk(query_structure.get('having'), 'having')
    return filter_keys


def _find_aggregation_keys(query_structure, table_id):
    keys = []
    for agg in query_structure.get('aggregations', []):
        if agg.get('tableId') == table_id:
            keys.append(f'agg:{table_id}.{agg.get("columnName")}:{agg.get("function")}')
    return keys


def parse_plan_row(row, alias_map):
    """Parse a single EXPLAIN QUERY PLAN row into a structured operation."""
    if isinstance(row, (tuple, list)):
        if len(row) >= 4:
            node_id, parent_id, _, detail = row[0], row[1], row[2], row[3]
        elif len(row) >= 3:
            node_id, parent_id, detail = row[0], row[1], row[2]
        else:
            return None
    elif isinstance(row, dict):
        node_id = row.get('id')
        parent_id = row.get('parent')
        detail = row.get('detail', '')
    else:
        return None

    detail = str(detail) if detail is not None else ''
    op = {
        'nodeId': int(node_id) if node_id is not None else None,
        'parentId': int(parent_id) if parent_id is not None else None,
        'detail': detail,
        'operation': None,
        'tableName': None,
        'tableAlias': None,
        'tableId': None,
        'indexName': None,
        'joinId': None,
        'astNodeKeys': [],
        'category': None,
    }

    for pattern, op_type in _SCAN_PATTERNS:
        m = pattern.search(detail)
        if m:
            op['operation'] = op_type
            raw_name = _strip_quotes(m.group(1))
            raw_alias = None
            if m.lastindex and m.lastindex >= 2 and m.group(2):
                raw_alias = _strip_quotes(m.group(2))

            if raw_alias:
                op['tableName'] = raw_name
                op['tableAlias'] = raw_alias
            else:
                op['tableAlias'] = raw_name
                op['tableName'] = raw_name

            mapped = alias_map.get(raw_alias or raw_name) or \
                     alias_map.get(raw_name) or \
                     alias_map.get((raw_alias or raw_name or '').lower()) or \
                     alias_map.get((raw_name or '').lower())
            if mapped:
                op['tableId'] = mapped['tableId']
                op['tableName'] = mapped['tableName']
                op['astNodeKeys'].append(f'table:{mapped["tableId"]}')

            if _PK_LOOKUP_PATTERN.search(detail):
                op['indexName'] = 'INTEGER PRIMARY KEY'
                op['category'] = 'index_access'
            else:
                idx_match = _INDEX_PATTERN.search(detail)
                if idx_match:
                    op['indexName'] = _strip_quotes(idx_match.group(1))
                    op['category'] = 'index_access'
                else:
                    op['category'] = 'table_scan'
            return op

    for pattern, op_type in _COMPOUND_PATTERNS:
        if pattern.search(detail):
            op['operation'] = op_type
            op['category'] = 'compound'
            upper_detail = detail.upper()
            if 'GROUP BY' in upper_detail:
                op['astNodeKeys'].append('group_by')
            if 'ORDER BY' in upper_detail:
                op['astNodeKeys'].append('order_by')
            return op

    op['operation'] = 'OTHER'
    op['category'] = 'other'
    return op


def normalize_explain_plan(raw_rows, query_structure):
    """
    Parse EXPLAIN QUERY PLAN rows into structured operations and map them
    to AST node IDs. Returns a list of operation dicts.
    """
    alias_map = _build_alias_map(query_structure)
    operations = []

    for row in raw_rows:
        op = parse_plan_row(row, alias_map)
        if op is None:
            continue
        operations.append(op)

    # Enrich: find join IDs from parent-child scan relationships,
    # and also from flat sibling tables when joins exist.
    table_ops = [o for o in operations if o.get('tableId')]
    for i, op in enumerate(table_ops):
        parent_id = op.get('parentId')
        parent_op = None
        if parent_id is not None:
            parent_op = next(
                (o for o in operations if o.get('nodeId') == parent_id and o.get('tableId')),
                None
            )
        if parent_op and parent_op.get('tableId') != op.get('tableId'):
            join_id = _find_join_id(
                query_structure,
                parent_op['tableId'],
                op['tableId']
            )
            if join_id:
                op['joinId'] = join_id
                op['astNodeKeys'].append(f'join:{join_id}')

        # Add filter and aggregation references
        if op.get('tableId'):
            op['astNodeKeys'].extend(_find_filter_ids(query_structure, op['tableId']))
            op['astNodeKeys'].extend(_find_aggregation_keys(query_structure, op['tableId']))

    # Fallback: for flat plans where all table ops are siblings under root,
    # associate non-first table ops with joins connecting them to prior tables.
    if query_structure.get('joins'):
        joined_pairs = set()
        for join in query_structure['joins']:
            l = join.get('leftTableId')
            r = join.get('rightTableId')
            jid = join.get('id')
            if not l or not r or not jid:
                continue
            for op in table_ops:
                if op.get('joinId'):
                    continue
                tid = op.get('tableId')
                if tid == r or tid == l:
                    other = l if tid == r else r
                    if any(o.get('tableId') == other for o in table_ops):
                        op['joinId'] = jid
                        key = f'join:{jid}'
                        if key not in op['astNodeKeys']:
                            op['astNodeKeys'].append(key)
                        joined_pairs.add((l, r))

    # Deduplicate astNodeKeys
    for op in operations:
        op['astNodeKeys'] = sorted(set(op.get('astNodeKeys', [])))

    return operations


# ---------------------------------------------------------------------------
# Semantic operation fingerprint for stable diffing
# ---------------------------------------------------------------------------

def _operation_fingerprint(op):
    """
    Produce a stable semantic key for a plan operation that ignores:
    - node IDs (assigned per query execution)
    - parent IDs
    - ephemeral table instance IDs (remapped on reload)
    But captures:
    - table identity (tableName + alias)
    - operation type (SCAN/SEARCH)
    - index name
    - category
    """
    return (
        op.get('tableName') or '',
        op.get('tableAlias') or '',
        op.get('operation') or '',
        op.get('indexName') or '',
        op.get('category') or '',
    )


# ---------------------------------------------------------------------------
# Plan diff
# ---------------------------------------------------------------------------

def diff_plans(old_operations, new_operations):
    """
    Compare two normalized plan operation lists and return a change set.

    Changes are keyed by semantic AST node references (tableId, joinId,
    filter key, etc.), NOT by SQL line numbers or plan node IDs.

    Returns:
        {
          'added': [operation...],
          'removed': [operation...],
          'changed': [{'old': op, 'new': op, 'changedFields': [...]}],
          'astChanges': [
             {'astNodeKey': 'join:j1', 'changeType': 'join_algorithm',
              'oldValue': 'SCAN', 'newValue': 'SEARCH USING INDEX idx_x'}
          ],
          'summary': {'added': n, 'removed': n, 'changed': n}
        }
    """
    old_fingerprints = {}
    for op in old_operations:
        fp = _operation_fingerprint(op)
        old_fingerprints.setdefault(fp, []).append(op)

    new_fingerprints = {}
    for op in new_operations:
        fp = _operation_fingerprint(op)
        new_fingerprints.setdefault(fp, []).append(op)

    added = []
    removed = []
    unchanged_fps = set()

    for fp, ops in new_fingerprints.items():
        if fp not in old_fingerprints:
            added.extend(ops)
        else:
            unchanged_fps.add(fp)

    for fp, ops in old_fingerprints.items():
        if fp not in new_fingerprints:
            removed.extend(ops)

    # Detect changes: operations on the same table but with different access path
    changed = []
    ast_changes = []

    old_by_table = {}
    for op in old_operations:
        tid = op.get('tableId')
        if tid and op.get('operation') in ('SCAN', 'SEARCH'):
            old_by_table.setdefault(tid, []).append(op)

    new_by_table = {}
    for op in new_operations:
        tid = op.get('tableId')
        if tid and op.get('operation') in ('SCAN', 'SEARCH'):
            new_by_table.setdefault(tid, []).append(op)

    all_table_ids = set(old_by_table.keys()) | set(new_by_table.keys())

    for tid in all_table_ids:
        old_ops = old_by_table.get(tid, [])
        new_ops = new_by_table.get(tid, [])

        old_access = _summarize_access(old_ops)
        new_access = _summarize_access(new_ops)

        if old_access != new_access and old_ops and new_ops:
            old_op = old_ops[0]
            new_op = new_ops[0]
            changed_fields = []
            if old_access.get('operation') != new_access.get('operation'):
                changed_fields.append('operation')
            if old_access.get('indexName') != new_access.get('indexName'):
                changed_fields.append('indexName')
            if old_access.get('category') != new_access.get('category'):
                changed_fields.append('category')

            if changed_fields:
                changed.append({
                    'tableId': tid,
                    'tableName': new_op.get('tableName') or old_op.get('tableName'),
                    'old': _public_op(old_op),
                    'new': _public_op(new_op),
                    'changedFields': changed_fields,
                    'astNodeKeys': sorted(set(
                        (new_op.get('astNodeKeys') or []) +
                        (old_op.get('astNodeKeys') or [])
                    )),
                })

                for key in sorted(set(
                    (new_op.get('astNodeKeys') or []) +
                    (old_op.get('astNodeKeys') or [])
                )):
                    change_type = _classify_ast_change(key, old_access, new_access)
                    ast_changes.append({
                        'astNodeKey': key,
                        'tableId': tid,
                        'changeType': change_type,
                        'oldValue': _access_label(old_access),
                        'newValue': _access_label(new_access),
                    })

    added_public = [_public_op(op) for op in added]
    removed_public = [_public_op(op) for op in removed]

    return {
        'added': added_public,
        'removed': removed_public,
        'changed': changed,
        'astChanges': ast_changes,
        'summary': {
            'added': len(added_public),
            'removed': len(removed_public),
            'changed': len(changed),
            'hasChanges': bool(added_public or removed_public or changed),
        },
    }


def _summarize_access(ops):
    if not ops:
        return {'operation': None, 'indexName': None, 'category': None}
    op = ops[0]
    return {
        'operation': op.get('operation'),
        'indexName': op.get('indexName'),
        'category': op.get('category'),
    }


def _access_label(access):
    parts = [access.get('operation') or 'NONE']
    if access.get('indexName'):
        parts.append(f"USING INDEX {access['indexName']}")
    return ' '.join(parts)


def _classify_ast_change(ast_key, old_access, new_access):
    if ast_key.startswith('join:'):
        if old_access.get('category') == 'table_scan' and new_access.get('category') == 'index_access':
            return 'join_index_added'
        if old_access.get('category') == 'index_access' and new_access.get('category') == 'table_scan':
            return 'join_index_removed'
        return 'join_access_changed'
    if ast_key.startswith('filter:'):
        if old_access.get('operation') == 'SCAN' and new_access.get('operation') == 'SEARCH':
            return 'filter_uses_index'
        if old_access.get('operation') == 'SEARCH' and new_access.get('operation') == 'SCAN':
            return 'filter_index_dropped'
        return 'filter_access_changed'
    if ast_key.startswith('agg:'):
        return 'aggregation_access_changed'
    if ast_key.startswith('table:'):
        if old_access.get('category') == 'table_scan' and new_access.get('category') == 'index_access':
            return 'table_index_added'
        return 'table_access_changed'
    if ast_key in ('group_by', 'order_by'):
        return f'{ast_key}_plan_changed'
    return 'plan_changed'


def _public_op(op):
    """Return a JSON-serializable view of an operation without internal fields."""
    return {
        'operation': op.get('operation'),
        'tableName': op.get('tableName'),
        'tableAlias': op.get('tableAlias'),
        'tableId': op.get('tableId'),
        'indexName': op.get('indexName'),
        'joinId': op.get('joinId'),
        'category': op.get('category'),
        'astNodeKeys': op.get('astNodeKeys', []),
        'detail': op.get('detail'),
    }


# ---------------------------------------------------------------------------
# High-level snapshot creation
# ---------------------------------------------------------------------------

def create_snapshot(query_structure, raw_plan_rows, row_count, duration_ms,
                    parameters=None, template_id=None, template_version=None,
                    label=None):
    """Build a complete snapshot dict ready for storage."""
    ast_hash = compute_ast_hash(query_structure)
    param_summary = compute_param_type_summary(parameters)
    operations = normalize_explain_plan(raw_plan_rows, query_structure)

    return {
        'template_id': template_id,
        'template_version': template_version,
        'label': label,
        'ast_hash': ast_hash,
        'param_type_summary': param_summary,
        'normalized_plan': [_public_op(op) for op in operations],
        'plan_operations': operations,
        'row_count': row_count,
        'duration_ms': round(duration_ms, 2),
        'query_structure': deepcopy(query_structure),
    }
