"""Execution-plan normalization and comparison.

- ``ast_hash``: canonical form of a query AST. Non-semantic formatting
  differences (key order, canvas positions, node ids, array order, parameter
  *values*) hash identically; semantic changes (JOIN type, filter operator,
  aggregation, selected columns) hash differently.
- ``params_summary``: type tags only, never raw parameter values.
- ``normalize_explain_plan``: SQLite EXPLAIN QUERY PLAN rows normalized to
  table access nodes (alias resolved back to the base table).
- ``diff_query_structures`` / ``diff_plans``: deterministic change sets
  keyed by AST node identity (never by SQL string position).
"""
import hashlib
import json
import re


# ---------------------------------------------------------------------------
# Canonical AST / hashing
# ---------------------------------------------------------------------------

def _canonical_aliases(tables):
    """Map table-instance id -> alias, mirroring the generator's derivation
    for missing aliases (tableName, tableName_2, ...)."""
    aliases = {}
    used = set()
    for table in tables or []:
        alias = table.get('alias')
        if not alias:
            base = table.get('tableName')
            alias = base
            n = 2
            while alias in used:
                alias = f'{base}_{n}'
                n += 1
        aliases[table.get('id')] = alias
        used.add(alias)
    return aliases


def _canon_tree(node, alias_of):
    if not isinstance(node, dict):
        return None
    if 'op' in node and 'children' in node:
        op = node.get('op')
        children = [
            c for c in (_canon_tree(child, alias_of) for child in node.get('children') or [])
            if c is not None
        ]
        if op == 'NOT':
            return {'not': children[0] if children else None}
        children.sort(key=lambda c: json.dumps(c, sort_keys=True))
        return {'op': op, 'children': children}
    if 'cmp' in node:
        out = {
            'table': alias_of(node.get('tableId')),
            'column': node.get('columnName'),
            'cmp': node.get('cmp'),
            # NOTE: the literal value is deliberately excluded; parameter
            # values are not part of the query's semantic identity.
        }
        if node.get('function'):
            out['function'] = node['function']
        if 'subquery' in node:
            out['subquery'] = canonicalize_query(node['subquery'] or {})
        return out
    return None


def canonicalize_query(query):
    query = query or {}
    aliases = _canonical_aliases(query.get('tables'))

    def alias_of(table_id):
        return aliases.get(table_id, str(table_id))

    tables = sorted(
        ({'tableName': t.get('tableName'), 'alias': aliases.get(t.get('id'))}
         for t in query.get('tables') or []),
        key=lambda d: d['alias'],
    )

    joins = []
    for join in query.get('joins') or []:
        jtype = join.get('type')
        if jtype == 'CROSS':
            pair = sorted([alias_of(join.get('leftTableId')), alias_of(join.get('rightTableId'))])
            joins.append({'type': jtype, 'a': pair[0], 'b': pair[1]})
        else:
            left = (alias_of(join.get('leftTableId')), join.get('leftColumn'))
            right = (alias_of(join.get('rightTableId')), join.get('rightColumn'))
            if jtype == 'INNER' and right < left:
                left, right = right, left
            joins.append({'type': jtype, 'left': left, 'right': right})
    joins.sort(key=lambda d: json.dumps(d, sort_keys=True))

    fields = sorted(
        ({'table': alias_of(f.get('tableId')),
          'column': f.get('columnName'),
          'as': f.get('alias') or ''}
         for f in query.get('selectedFields') or []),
        key=lambda d: json.dumps(d, sort_keys=True),
    )

    aggregations = sorted(
        ({'table': alias_of(a.get('tableId')),
          'column': a.get('columnName'),
          'function': a.get('function'),
          'as': a.get('alias') or ''}
         for a in query.get('aggregations') or []),
        key=lambda d: json.dumps(d, sort_keys=True),
    )

    ctes = sorted(
        ({'name': c.get('name'), 'query': canonicalize_query(c.get('queryStructure'))}
         for c in query.get('ctes') or []),
        key=lambda d: d['name'],
    )

    return {
        'tables': tables,
        'joins': joins,
        'fields': fields,
        'aggregations': aggregations,
        'where': _canon_tree(query.get('where'), alias_of),
        'having': _canon_tree(query.get('having'), alias_of),
        'ctes': ctes,
        # limit / offset are parameter values, not query identity
    }


def ast_hash(query):
    canonical = canonicalize_query(query)
    payload = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Parameter type summary (never raw values)
# ---------------------------------------------------------------------------

def _type_tag(value):
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
    if isinstance(value, (list, tuple)):
        item_tags = {_type_tag(v) for v in value}
        item = item_tags.pop() if len(item_tags) == 1 else 'mixed'
        return f'{item}[]' if item != 'mixed' else 'mixed[]'
    return type(value).__name__


def params_summary(params):
    """{param_name: type_tag} — contains no raw parameter values."""
    return {name: _type_tag(value) for name, value in (params or {}).items()}


# ---------------------------------------------------------------------------
# EXPLAIN QUERY PLAN normalization
# ---------------------------------------------------------------------------

_SCAN_RE = re.compile(r'^(SCAN|SEARCH)\s+(.+)$')
_INDEX_RE = re.compile(r'USING\s+(COVERING INDEX|INDEX)\s+([^\s(]+)')
_AUTO_INDEX_RE = re.compile(r'USING\s+AUTOMATIC\s+(COVERING\s+)?INDEX')
_PK_RE = re.compile(r'USING\s+INTEGER PRIMARY KEY')
_USING_RE = re.compile(r'\(([^()]*)\)\s*$')
_TABLE_RE = re.compile(r'^([^\s]+)(?:\s+AS\s+([^\s]+))?$', re.IGNORECASE)


def normalize_explain_plan(rows, alias_map=None):
    """Normalize EXPLAIN QUERY PLAN rows to a stable, comparable shape.

    ``alias_map`` maps table alias -> base table name (built from the AST).
    Returns {'nodes': [...], 'extras': [...]} where each node references a
    table access (never a SQL string position)."""
    alias_map = dict(alias_map or {})
    nodes = []
    extras = []

    for row in rows:
        detail = row[3] if isinstance(row, (tuple, list)) else row.get('detail', '')
        match = _SCAN_RE.match(detail or '')
        if not match:
            if detail:
                extras.append(detail)
            continue

        op = match.group(1)
        rest = match.group(2).strip()

        index = None
        index_kind = None
        index_match = _INDEX_RE.search(rest)
        auto_match = _AUTO_INDEX_RE.search(rest)
        pk_match = _PK_RE.search(rest)
        if index_match:
            index_kind = index_match.group(1)
            index = index_match.group(2)
        elif auto_match:
            index_kind = 'AUTOMATIC COVERING INDEX' if auto_match.group(1) else 'AUTOMATIC INDEX'
            index = 'AUTOMATIC'
        elif pk_match:
            index_kind = 'INTEGER PRIMARY KEY'
            index = 'INTEGER PRIMARY KEY'

        using = None
        using_match = _USING_RE.search(rest)
        if using_match:
            using = using_match.group(1)

        table_part = rest
        if index_match:
            table_part = rest[:index_match.start()].strip()
        elif auto_match:
            table_part = rest[:auto_match.start()].strip()
        elif pk_match:
            table_part = rest[:pk_match.start()].strip()
        elif using_match:
            table_part = rest[:using_match.start()].strip()

        name = table_part
        alias = None
        table_match = _TABLE_RE.match(table_part)
        if table_match:
            name = table_match.group(1)
            alias = table_match.group(2)

        base_table = alias_map.get(name, name)
        if alias:
            base_table = alias_map.get(alias, base_table)

        if op == 'SCAN':
            access = 'covering-index' if index_kind in ('COVERING INDEX', 'AUTOMATIC COVERING INDEX') else 'full-scan'
        elif index_kind == 'COVERING INDEX':
            access = 'covering-index'
        else:
            access = 'index'

        nodes.append({
            'op': op,
            'table': base_table,
            'alias': alias or (name if name != base_table else None),
            'index': index,
            'using': using,
            'access': access,
        })

    return {'nodes': nodes, 'extras': sorted(set(extras))}


# ---------------------------------------------------------------------------
# Change sets (keyed by AST node identity)
# ---------------------------------------------------------------------------

def _collect_clauses(tree, kind, alias_of):
    """Flatten a condition tree to clauses keyed by
    (kind, tableAlias, column, occurrenceIndex). The occurrence index is
    assigned in canonical order (cmp, then node id) so reordering children
    in the AST never changes the pairing."""
    flat = []

    def visit(node):
        if not isinstance(node, dict):
            return
        if 'op' in node and 'children' in node:
            for child in node.get('children') or []:
                visit(child)
        elif 'cmp' in node:
            flat.append(node)

    visit(tree)

    collected = {}
    groups = {}
    for node in flat:
        base = (kind, alias_of(node.get('tableId')), node.get('columnName'))
        groups.setdefault(base, []).append(node)
    for base, nodes in groups.items():
        nodes.sort(key=lambda n: (str(n.get('cmp')), str(n.get('id'))))
        for index, node in enumerate(nodes):
            collected[(*base, index)] = node
    return collected


def _clause_label(node, alias_of):
    label = f"{alias_of(node.get('tableId'))}.{node.get('columnName')}"
    if node.get('function'):
        label = f"{node['function']}({label})"
    return f'{label} {node.get("cmp")}'


def diff_query_structures(query_a, query_b):
    """Structural change set between two ASTs, localized to AST nodes.
    Parameter *value* differences are ignored by design."""
    changes = []
    alias_a = _canonical_aliases(query_a.get('tables') if query_a else [])
    alias_b = _canonical_aliases(query_b.get('tables') if query_b else [])
    query_a = query_a or {}
    query_b = query_b or {}

    def of_a(tid):
        return alias_a.get(tid, str(tid))

    def of_b(tid):
        return alias_b.get(tid, str(tid))

    # --- table instances (keyed by alias: the semantic instance identity)
    tabs_a = {alias_a[t.get('id')]: t for t in query_a.get('tables') or []}
    tabs_b = {alias_b[t.get('id')]: t for t in query_b.get('tables') or []}
    for alias in sorted(tabs_a.keys() - tabs_b.keys()):
        table = tabs_a[alias]
        changes.append({'category': 'table', 'change': 'removed',
                        'nodeId': table.get('id'), 'alias': alias,
                        'label': f"{table.get('tableName')} {alias}"})
    for alias in sorted(tabs_b.keys() - tabs_a.keys()):
        table = tabs_b[alias]
        changes.append({'category': 'table', 'change': 'added',
                        'nodeId': table.get('id'), 'alias': alias,
                        'label': f"{table.get('tableName')} {alias}"})

    # --- joins (keyed by endpoint table aliases + columns, type-independent)
    def join_key(join, alias_of):
        pair = [
            (alias_of(join.get('leftTableId')), join.get('leftColumn') or ''),
            (alias_of(join.get('rightTableId')), join.get('rightColumn') or ''),
        ]
        pair.sort(key=lambda p: json.dumps(p))
        return tuple(pair)

    def join_label(join, alias_of):
        if join.get('type') == 'CROSS':
            return (f"CROSS {alias_of(join.get('leftTableId'))} × "
                    f"{alias_of(join.get('rightTableId'))}")
        return (f"{alias_of(join.get('leftTableId'))}.{join.get('leftColumn')} = "
                f"{alias_of(join.get('rightTableId'))}.{join.get('rightColumn')}")

    joins_a = {join_key(j, of_a): j for j in query_a.get('joins') or []}
    joins_b = {join_key(j, of_b): j for j in query_b.get('joins') or []}
    for key in sorted(joins_a.keys() - joins_b.keys()):
        join = joins_a[key]
        changes.append({'category': 'join', 'change': 'removed',
                        'nodeId': join.get('id'), 'label': join_label(join, of_a),
                        'detail': {'type': join.get('type')}})
    for key in sorted(joins_b.keys() - joins_a.keys()):
        join = joins_b[key]
        changes.append({'category': 'join', 'change': 'added',
                        'nodeId': join.get('id'), 'label': join_label(join, of_b),
                        'detail': {'type': join.get('type')}})
    for key in sorted(joins_a.keys() & joins_b.keys()):
        ja, jb = joins_a[key], joins_b[key]
        if ja.get('type') != jb.get('type'):
            changes.append({'category': 'join', 'change': 'modified',
                            'nodeId': jb.get('id'), 'label': join_label(jb, of_b),
                            'detail': {'from': ja.get('type'), 'to': jb.get('type')}})

    # --- filters (where / having clauses keyed by kind+tableAlias+column+idx)
    for kind in ('where', 'having'):
        clauses_a = _collect_clauses(query_a.get(kind), kind, of_a)
        clauses_b = _collect_clauses(query_b.get(kind), kind, of_b)
        category = 'filter' if kind == 'where' else 'having'
        for key in sorted(clauses_a.keys() - clauses_b.keys()):
            node = clauses_a[key]
            changes.append({'category': category, 'change': 'removed',
                            'nodeId': node.get('id'), 'label': _clause_label(node, of_a)})
        for key in sorted(clauses_b.keys() - clauses_a.keys()):
            node = clauses_b[key]
            changes.append({'category': category, 'change': 'added',
                            'nodeId': node.get('id'), 'label': _clause_label(node, of_b)})
        for key in sorted(clauses_a.keys() & clauses_b.keys()):
            na, nb = clauses_a[key], clauses_b[key]
            if na.get('cmp') != nb.get('cmp') or na.get('function') != nb.get('function'):
                changes.append({'category': category, 'change': 'modified',
                                'nodeId': nb.get('id'), 'label': _clause_label(nb, of_b),
                                'detail': {'from': na.get('cmp'), 'to': nb.get('cmp')}})

    # group-logic flip with identical clause multiset (AND <-> OR / NOT)
    for kind in ('where', 'having'):
        tree_a = _canon_tree(query_a.get(kind), of_a)
        tree_b = _canon_tree(query_b.get(kind), of_b)
        if tree_a == tree_b or tree_a is None or tree_b is None:
            continue
        if _collect_clauses(query_a.get(kind), kind, of_a).keys() == \
           _collect_clauses(query_b.get(kind), kind, of_b).keys():
            changes.append({'category': 'filter', 'change': 'modified',
                            'nodeId': (query_b.get(kind) or {}).get('id'),
                            'label': f'{kind.upper()} group logic',
                            'detail': {'from': (query_a.get(kind) or {}).get('op'),
                                       'to': (query_b.get(kind) or {}).get('op')}})

    # --- aggregations (keyed by tableAlias + column)
    def agg_key(agg, alias_of):
        return (alias_of(agg.get('tableId')), agg.get('columnName'))

    aggs_a = {agg_key(a, of_a): a for a in query_a.get('aggregations') or []}
    aggs_b = {agg_key(a, of_b): a for a in query_b.get('aggregations') or []}
    for key in sorted(aggs_a.keys() - aggs_b.keys()):
        agg = aggs_a[key]
        changes.append({'category': 'aggregation', 'change': 'removed',
                        'nodeId': None,
                        'label': f"{agg.get('function')}({key[0]}.{key[1]})"})
    for key in sorted(aggs_b.keys() - aggs_a.keys()):
        agg = aggs_b[key]
        changes.append({'category': 'aggregation', 'change': 'added',
                        'nodeId': None,
                        'label': f"{agg.get('function')}({key[0]}.{key[1]})"})
    for key in sorted(aggs_a.keys() & aggs_b.keys()):
        ga, gb = aggs_a[key], aggs_b[key]
        if ga.get('function') != gb.get('function'):
            changes.append({'category': 'aggregation', 'change': 'modified',
                            'nodeId': None,
                            'label': f"{gb.get('function')}({key[0]}.{key[1]})",
                            'detail': {'from': ga.get('function'), 'to': gb.get('function')}})

    # --- selected fields
    def field_key(field, alias_of):
        return (alias_of(field.get('tableId')), field.get('columnName'))

    fields_a = {field_key(f, of_a): f for f in query_a.get('selectedFields') or []}
    fields_b = {field_key(f, of_b): f for f in query_b.get('selectedFields') or []}
    for key in sorted(fields_a.keys() - fields_b.keys()):
        changes.append({'category': 'select', 'change': 'removed',
                        'nodeId': None, 'label': f'{key[0]}.{key[1]}'})
    for key in sorted(fields_b.keys() - fields_a.keys()):
        changes.append({'category': 'select', 'change': 'added',
                        'nodeId': None, 'label': f'{key[0]}.{key[1]}'})

    # --- pagination (structural presence, values themselves excluded)
    for name in ('limit', 'offset'):
        if (query_a.get(name) or 0) != (query_b.get(name) or 0):
            changes.append({'category': 'pagination', 'change': 'modified',
                            'nodeId': None, 'label': name,
                            'detail': {'from': query_a.get(name) or 0,
                                       'to': query_b.get(name) or 0}})

    return changes


def diff_plans(plan_a, plan_b):
    """Access-path change set between two normalized plans, keyed by the
    table/alias access node (index usage changes included)."""
    changes = []

    def node_key(node):
        return (node.get('alias') or node.get('table'), node.get('table'))

    nodes_a = {node_key(n): n for n in (plan_a or {}).get('nodes', [])}
    nodes_b = {node_key(n): n for n in (plan_b or {}).get('nodes', [])}

    for key in sorted(nodes_a.keys() - nodes_b.keys()):
        node = nodes_a[key]
        changes.append({'category': 'access-path', 'change': 'removed',
                        'table': node.get('table'), 'alias': node.get('alias'),
                        'detail': {'access': node.get('access'), 'index': node.get('index')}})
    for key in sorted(nodes_b.keys() - nodes_a.keys()):
        node = nodes_b[key]
        changes.append({'category': 'access-path', 'change': 'added',
                        'table': node.get('table'), 'alias': node.get('alias'),
                        'detail': {'access': node.get('access'), 'index': node.get('index')}})
    for key in sorted(nodes_a.keys() & nodes_b.keys()):
        na, nb = nodes_a[key], nodes_b[key]
        if (na.get('op'), na.get('index')) != (nb.get('op'), nb.get('index')):
            changes.append({
                'category': 'access-path', 'change': 'modified',
                'table': nb.get('table'), 'alias': nb.get('alias'),
                'detail': {
                    'from': {'op': na.get('op'), 'access': na.get('access'),
                             'index': na.get('index')},
                    'to': {'op': nb.get('op'), 'access': nb.get('access'),
                           'index': nb.get('index')},
                },
            })

    extras_a = set((plan_a or {}).get('extras', []))
    extras_b = set((plan_b or {}).get('extras', []))
    for extra in sorted(extras_b - extras_a):
        changes.append({'category': 'access-path', 'change': 'added',
                        'table': None, 'alias': None, 'detail': {'extra': extra}})
    for extra in sorted(extras_a - extras_b):
        changes.append({'category': 'access-path', 'change': 'removed',
                        'table': None, 'alias': None, 'detail': {'extra': extra}})

    return changes
