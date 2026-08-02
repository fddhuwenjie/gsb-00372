"""Execution-plan analysis for version comparison.

This module turns a query into three comparable artifacts:

  * a *stable AST hash* -- a canonical fingerprint of query semantics that is
    invariant to non-semantic edits (join / filter authoring order, alias
    renaming, node position, and literal parameter values) but changes when a
    real JOIN, filter or aggregation changes;
  * a *parameter type summary* -- the types of the bound parameters only, so
    plans can be compared without ever recording sensitive parameter values;
  * a *normalized plan* -- the SQLite EXPLAIN QUERY PLAN mapped onto semantic
    access nodes keyed by AST identity (table instance / index access), never
    by SQL text line numbers.

The diff between two versions is expressed as a change set located to concrete
AST node kinds: join, filter, aggregation and (index) access.
"""
import hashlib
import json
import re

from app.services.security_service import SecurityService

# ---- parameter type summary ------------------------------------------------

def _value_type(value):
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'number'
    if value is None:
        return 'null'
    if isinstance(value, str):
        # Recognise ISO dates so a date filter reads as 'date' not 'string'.
        if re.match(r'^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$', value):
            return 'date'
        return 'string'
    if isinstance(value, list):
        return 'list'
    return 'unknown'


def summarize_param_types(params):
    """Types only -- never the raw values. Returns an ordered {name: type}
    map plus a type histogram, both safe to persist."""
    params = params or {}
    by_name = {}
    histogram = {}
    for name in sorted(params.keys(), key=_param_sort_key):
        t = _value_type(params[name])
        by_name[name] = t
        histogram[t] = histogram.get(t, 0) + 1
    return {'byName': by_name, 'histogram': histogram, 'count': len(by_name)}


def _param_sort_key(name):
    m = re.match(r'^p(\d+)$', name)
    return (0, int(m.group(1))) if m else (1, name)


class PlanAnalysisService:
    # ================================================================ AST hash
    @staticmethod
    def canonicalize_ast(query_structure):
        """Produce an isomorphism-tolerant canonical form of the query AST.

        Table instances are relabelled to canonical tokens (t0, t1, ...) derived
        from their table name and the roles they play, so arbitrary instance ids
        and aliases do not affect the hash. Joins and boolean children are
        sorted; parameter values are reduced to type tokens.
        """
        qs = query_structure or {}
        label_map = PlanAnalysisService._canonical_labels(qs)

        joins = [
            PlanAnalysisService._canon_join(j, label_map)
            for j in qs.get('joins', [])
        ]
        joins.sort(key=lambda d: json.dumps(d, sort_keys=True))

        selected = [
            {'table': label_map[f['tableId']], 'column': f['columnName']}
            for f in qs.get('selectedFields', []) if f['tableId'] in label_map
        ]
        selected.sort(key=lambda d: (d['table'], d['column']))

        aggregations = [
            {'table': label_map[a['tableId']], 'column': a['columnName'],
             'function': a['function']}
            for a in qs.get('aggregations', []) if a['tableId'] in label_map
        ]
        aggregations.sort(key=lambda d: (d['function'], d['table'], d['column']))

        order_by = [
            {'table': label_map[o['tableId']], 'column': o['columnName'],
             'direction': (o.get('direction') or 'ASC').upper(),
             'function': o.get('function')}
            for o in (qs.get('orderBy') or []) if o['tableId'] in label_map
        ]

        tables = sorted(label_map.values())

        canonical = {
            'tables': tables,
            'joins': joins,
            'selectedFields': selected,
            'aggregations': aggregations,
            'orderBy': order_by,
            'where': PlanAnalysisService._canon_condition(qs.get('where'), label_map),
            'having': PlanAnalysisService._canon_condition(qs.get('having'), label_map),
            # Presence, not concrete value, of pagination.
            'hasLimit': qs.get('limit') is not None,
            'hasOffset': bool(qs.get('offset')),
        }
        return canonical

    @staticmethod
    def _canonical_labels(qs):
        """Assign canonical labels to table instances. Instances with the same
        table name and the same participation fingerprint are interchangeable
        (true symmetry), so their relative order does not matter."""
        tables = qs.get('tables', [])
        fingerprints = {}
        for t in tables:
            fingerprints[t['id']] = PlanAnalysisService._instance_fingerprint(t, qs)

        ordered = sorted(
            tables,
            key=lambda t: (t['tableName'], fingerprints[t['id']], t['id']),
        )
        return {t['id']: f't{i}' for i, t in enumerate(ordered)}

    @staticmethod
    def _instance_fingerprint(table, qs):
        """A stable description of how a table instance is used, independent of
        its id/alias. Used only to order self-join instances deterministically."""
        tid = table['id']
        parts = [f"name={table['tableName']}"]
        for f in qs.get('selectedFields', []):
            if f['tableId'] == tid:
                parts.append(f"sel:{f['columnName']}")
        for a in qs.get('aggregations', []):
            if a['tableId'] == tid:
                parts.append(f"agg:{a['function']}:{a['columnName']}")
        for j in qs.get('joins', []):
            if j.get('leftTableId') == tid:
                parts.append(f"jl:{j.get('leftColumn')}:{j.get('type')}")
            if j.get('rightTableId') == tid:
                parts.append(f"jr:{j.get('rightColumn')}:{j.get('type')}")

        def scan(node):
            if not isinstance(node, dict):
                return
            if node.get('tableId') == tid and 'cmp' in node:
                parts.append(f"flt:{node.get('columnName')}:{node.get('cmp')}")
            for c in node.get('children', []) or []:
                scan(c)
        scan(qs.get('where'))
        scan(qs.get('having'))
        return ','.join(sorted(parts))

    @staticmethod
    def _canon_join(join, label_map):
        left = label_map.get(join.get('leftTableId'))
        right = label_map.get(join.get('rightTableId'))
        left_col = join.get('leftColumn')
        right_col = join.get('rightColumn')
        # Order the two sides canonically for non-directional join types so
        # that swapping table order does not appear as a change; keep direction
        # for LEFT joins where side matters.
        jtype = join.get('type')
        if jtype in ('INNER', 'CROSS'):
            pair = sorted([(left, left_col), (right, right_col)])
            (a, ac), (b, bc) = pair[0], pair[1]
            return {'type': jtype, 'a': a, 'aColumn': ac, 'b': b, 'bColumn': bc}
        return {'type': jtype, 'a': left, 'aColumn': left_col,
                'b': right, 'bColumn': right_col}

    @staticmethod
    def _canon_condition(node, label_map):
        if not node:
            return None
        op = node.get('op')
        if op in ('AND', 'OR', 'NOT') and 'children' in node:
            children = [
                PlanAnalysisService._canon_condition(c, label_map)
                for c in node['children']
            ]
            children = [c for c in children if c is not None]
            if op in ('AND', 'OR'):
                children.sort(key=lambda d: json.dumps(d, sort_keys=True))
            return {'op': op, 'children': children}
        if 'cmp' in node:
            leaf = {
                'table': label_map.get(node.get('tableId')),
                'column': node.get('columnName'),
                'cmp': node.get('cmp'),
                'function': node.get('function'),
            }
            if node.get('subquery'):
                leaf['subquery'] = PlanAnalysisService.canonicalize_ast(node['subquery'])
            return leaf
        return None

    @staticmethod
    def ast_hash(query_structure):
        canonical = PlanAnalysisService.canonicalize_ast(query_structure)
        blob = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(blob.encode('utf-8')).hexdigest()

    # ============================================================ plan normalize
    @staticmethod
    def normalize_plan(raw_plan_rows, query_structure):
        """Map EXPLAIN QUERY PLAN rows onto AST-keyed access nodes.

        The generated SQL references each table by its alias, so a plan row like
        ``SCAN o`` / ``SEARCH c USING INDEX ...`` is matched back to the table
        instance (and thus its canonical label), never to a SQL line number.
        """
        qs = query_structure or {}
        label_map = PlanAnalysisService._canonical_labels(qs)
        alias_to_id = {t['alias']: t['id'] for t in qs.get('tables', [])}
        name_to_ids = {}
        for t in qs.get('tables', []):
            name_to_ids.setdefault(t['tableName'], []).append(t['id'])

        accesses = []
        uses_temp_btree_order = False
        uses_temp_btree_group = False
        uses_temp_btree_distinct = False
        subquery_flatten = False

        for row in raw_plan_rows:
            detail = row[3] if isinstance(row, (tuple, list)) else row.get('detail')
            if not detail:
                continue
            up = detail.upper()
            if 'USE TEMP B-TREE FOR ORDER BY' in up:
                uses_temp_btree_order = True
            if 'USE TEMP B-TREE FOR GROUP BY' in up:
                uses_temp_btree_group = True
            if 'USE TEMP B-TREE FOR DISTINCT' in up:
                uses_temp_btree_distinct = True
            if 'CORRELATED' in up or 'SUBQUERY' in up:
                subquery_flatten = True

            access = PlanAnalysisService._parse_access(detail, alias_to_id, name_to_ids, label_map)
            if access:
                accesses.append(access)

        # Order accesses by their canonical table label so the normalized plan
        # is order-stable across runs.
        accesses.sort(key=lambda a: (a['tableRef'] or 'zzz', a['access'], a.get('index') or ''))

        return {
            'accesses': accesses,
            'usesTempBTreeForOrderBy': uses_temp_btree_order,
            'usesTempBTreeForGroupBy': uses_temp_btree_group,
            'usesTempBTreeForDistinct': uses_temp_btree_distinct,
            'usesSubquery': subquery_flatten,
        }

    @staticmethod
    def _parse_access(detail, alias_to_id, name_to_ids, label_map):
        # SCAN <alias|table>  |  SEARCH <alias|table> [USING [COVERING] INDEX <name>]
        m = re.search(r'\b(SCAN|SEARCH)\b\s+(?:TABLE\s+)?([a-zA-Z_][a-zA-Z0-9_]*)', detail, re.IGNORECASE)
        if not m:
            return None
        access = m.group(1).lower()
        token = m.group(2)

        table_id = alias_to_id.get(token)
        if table_id is None:
            # Fall back to a unique table name match.
            ids = name_to_ids.get(token)
            if ids and len(ids) == 1:
                table_id = ids[0]

        table_ref = label_map.get(table_id) if table_id else None

        index_match = re.search(
            r'USING\s+(?:COVERING\s+)?INDEX\s+([a-zA-Z_][a-zA-Z0-9_]*)',
            detail, re.IGNORECASE,
        )
        auto_index = 'AUTOMATIC' in detail.upper()
        index_name = index_match.group(1) if index_match else None
        is_full_scan = (access == 'scan') and index_name is None

        return {
            'astNodeKind': 'access',
            'tableRef': table_ref,
            'alias': token if token in alias_to_id else None,
            'access': access,
            'index': index_name,
            'automaticIndex': auto_index,
            'isFullScan': is_full_scan,
        }

    # ============================================================ change set
    @staticmethod
    def diff_ast(canonical_a, canonical_b):
        """Compute a change set between two canonical ASTs, located to node
        kind (join / filter / aggregation / field / orderBy)."""
        changes = []

        def pair_key(j):
            # Unordered table-pair + columns identity, independent of join type
            # and of which side each table sits on.
            ends = sorted([(j['a'], j['aColumn']), (j['b'], j['bColumn'])])
            return json.dumps(ends, sort_keys=True)

        # Joins: match on the unordered end-pair so a type change (e.g. INNER ->
        # LEFT) reports as 'modified' rather than add+remove.
        ja = {pair_key(j): j for j in canonical_a.get('joins', [])}
        jb = {pair_key(j): j for j in canonical_b.get('joins', [])}
        for k in jb.keys() - ja.keys():
            changes.append({'kind': 'join', 'change': 'added', 'node': jb[k]})
        for k in ja.keys() - jb.keys():
            changes.append({'kind': 'join', 'change': 'removed', 'node': ja[k]})
        for k in ja.keys() & jb.keys():
            if ja[k]['type'] != jb[k]['type']:
                changes.append({'kind': 'join', 'change': 'modified',
                                'from': ja[k], 'to': jb[k]})

        # Filters: flatten leaves from where + having.
        fa = PlanAnalysisService._collect_filters(canonical_a)
        fb = PlanAnalysisService._collect_filters(canonical_b)
        PlanAnalysisService._diff_filters(fa, fb, changes)

        # Aggregations.
        PlanAnalysisService._diff_set(
            canonical_a.get('aggregations', []), canonical_b.get('aggregations', []),
            'aggregation', changes,
        )
        # Selected fields.
        PlanAnalysisService._diff_set(
            canonical_a.get('selectedFields', []), canonical_b.get('selectedFields', []),
            'field', changes,
        )
        # Order by.
        PlanAnalysisService._diff_set(
            canonical_a.get('orderBy', []), canonical_b.get('orderBy', []),
            'orderBy', changes,
        )
        return changes

    @staticmethod
    def _collect_filters(canonical):
        leaves = []

        def walk(node, path):
            if not node:
                return
            if 'op' in node:
                for i, c in enumerate(node.get('children', [])):
                    walk(c, path + [node['op']])
            elif 'cmp' in node:
                leaves.append(node)
        walk(canonical.get('where'), [])
        walk(canonical.get('having'), [])
        return leaves

    @staticmethod
    def _filter_identity(f):
        # Identity independent of the compared value type: table+column+cmp.
        return json.dumps({'table': f.get('table'), 'column': f.get('column'),
                           'cmp': f.get('cmp'), 'function': f.get('function')},
                          sort_keys=True)

    @staticmethod
    def _diff_filters(fa, fb, changes):
        ma = {PlanAnalysisService._filter_identity(f): f for f in fa}
        mb = {PlanAnalysisService._filter_identity(f): f for f in fb}
        for k in mb.keys() - ma.keys():
            changes.append({'kind': 'filter', 'change': 'added', 'node': mb[k]})
        for k in ma.keys() - mb.keys():
            changes.append({'kind': 'filter', 'change': 'removed', 'node': ma[k]})

    @staticmethod
    def _diff_set(list_a, list_b, kind, changes):
        sa = {json.dumps(x, sort_keys=True) for x in list_a}
        sb = {json.dumps(x, sort_keys=True) for x in list_b}
        for x in sb - sa:
            changes.append({'kind': kind, 'change': 'added', 'node': json.loads(x)})
        for x in sa - sb:
            changes.append({'kind': kind, 'change': 'removed', 'node': json.loads(x)})

    @staticmethod
    def diff_plan(plan_a, plan_b):
        """Diff two normalized plans, located to table access (AST) identity."""
        changes = []
        aa = {a['tableRef']: a for a in (plan_a or {}).get('accesses', [])}
        ab = {a['tableRef']: a for a in (plan_b or {}).get('accesses', [])}
        for ref in ab.keys() - aa.keys():
            changes.append({'kind': 'access', 'change': 'added', 'node': ab[ref]})
        for ref in aa.keys() - ab.keys():
            changes.append({'kind': 'access', 'change': 'removed', 'node': aa[ref]})
        for ref in aa.keys() & ab.keys():
            a, b = aa[ref], ab[ref]
            if (a['access'], a.get('index'), a['isFullScan']) != (
                    b['access'], b.get('index'), b['isFullScan']):
                changes.append({'kind': 'access', 'change': 'modified',
                                'tableRef': ref, 'from': a, 'to': b})
        for flag in ('usesTempBTreeForOrderBy', 'usesTempBTreeForGroupBy',
                     'usesTempBTreeForDistinct', 'usesSubquery'):
            if (plan_a or {}).get(flag) != (plan_b or {}).get(flag):
                changes.append({'kind': 'planFlag', 'change': 'modified', 'flag': flag,
                                'from': (plan_a or {}).get(flag),
                                'to': (plan_b or {}).get(flag)})
        return changes

    # ============================================================ full compare
    @staticmethod
    def compare_records(record_a, record_b):
        """Compare two captured plan records (dicts) and return a stable,
        AST-located change set plus cost deltas. Never exposes parameter values.
        """
        ca = record_a.get('canonical_ast') or {}
        cb = record_b.get('canonical_ast') or {}
        ast_changes = PlanAnalysisService.diff_ast(ca, cb)
        plan_changes = PlanAnalysisService.diff_plan(
            record_a.get('normalized_plan'), record_b.get('normalized_plan')
        )

        semantically_equal = record_a.get('ast_hash') == record_b.get('ast_hash')

        rows_a = record_a.get('row_count')
        rows_b = record_b.get('row_count')
        dur_a = record_a.get('duration_ms')
        dur_b = record_b.get('duration_ms')

        return {
            'astHashA': record_a.get('ast_hash'),
            'astHashB': record_b.get('ast_hash'),
            'semanticallyEqual': semantically_equal,
            'astChanges': ast_changes,
            'planChanges': plan_changes,
            'paramTypeSummaryA': record_a.get('param_type_summary'),
            'paramTypeSummaryB': record_b.get('param_type_summary'),
            'result': {
                'rowCountA': rows_a,
                'rowCountB': rows_b,
                'rowCountDelta': (rows_b - rows_a) if (rows_a is not None and rows_b is not None) else None,
                'durationMsA': dur_a,
                'durationMsB': dur_b,
                'durationMsDelta': round(dur_b - dur_a, 2) if (dur_a is not None and dur_b is not None) else None,
            },
            'changeCount': len(ast_changes) + len(plan_changes),
        }
