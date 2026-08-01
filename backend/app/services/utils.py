import string
import random
import re
from datetime import datetime, timedelta

BASE62_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits

def base62_encode(num, length=6):
    """Encode a number to base62 string with fixed length."""
    if num == 0:
        return BASE62_ALPHABET[0] * length
    result = []
    base = len(BASE62_ALPHABET)
    while num > 0 and len(result) < length:
        num, remainder = divmod(num, base)
        result.append(BASE62_ALPHABET[remainder])
    while len(result) < length:
        result.append(BASE62_ALPHABET[0])
    return ''.join(reversed(result))

def generate_token(length=6):
    """Generate a random base62 token."""
    return ''.join(random.choice(BASE62_ALPHABET) for _ in range(length))

def escape_sql_string(value):
    """Escape a string for safe SQL insertion."""
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        escaped = escaped.replace("\\", "\\\\")
        return f"'{escaped}'"
    return f"'{str(value)}'"

def replace_params_in_sql(sql, params):
    """Replace parameterized placeholders with actual values for export."""
    result = sql
    for key, value in sorted(params.items(), key=lambda x: -len(x[0])):
        placeholder = f':{key}'
        result = result.replace(placeholder, escape_sql_string(value))
    return result

def extract_cte_references(query_structure):
    """Extract all CTE name references from a query structure."""
    references = set()
    
    def scan_node(node):
        if isinstance(node, dict):
            if 'tableName' in node:
                references.add(node['tableName'])
            if 'subquery' in node and 'queryStructure' in node:
                scan_node(node['queryStructure'])
            for value in node.values():
                scan_node(value)
        elif isinstance(node, list):
            for item in node:
                scan_node(item)
    
    scan_node(query_structure)
    return references

def sort_ctes_by_dependency(ctes):
    """Sort CTEs in dependency order using topological sort."""
    if not ctes:
        return []
    
    cte_map = {cte['name']: cte for cte in ctes}
    cte_names = set(cte_map.keys())
    
    in_degree = {name: 0 for name in cte_names}
    graph = {name: [] for name in cte_names}
    
    for cte in ctes:
        refs = extract_cte_references(cte['queryStructure'])
        for ref in refs:
            if ref in cte_names and ref != cte['name']:
                graph[ref].append(cte['name'])
                in_degree[cte['name']] += 1
    
    queue = [name for name in cte_names if in_degree[name] == 0]
    result = []
    
    while queue:
        name = queue.pop(0)
        result.append(name)
        for neighbor in graph[name]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    if len(result) != len(cte_names):
        raise ValueError('Circular dependency detected in CTEs')
    
    return [cte_map[name] for name in result]

def detect_circular_dependency(ctes):
    """Check for circular dependencies in CTEs."""
    try:
        sort_ctes_by_dependency(ctes)
        return False
    except ValueError:
        return True

def validate_cte_names(ctes):
    """Validate CTE names are unique and valid identifiers."""
    names = []
    for cte in ctes:
        name = cte.get('name')
        if not name:
            raise ValueError('CTE name is required')
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
            raise ValueError(f'Invalid CTE name: {name}')
        if name in names:
            raise ValueError(f'Duplicate CTE name: {name}')
        names.append(name)
    return True

def parse_explain_query_plan(explain_rows):
    """Parse EXPLAIN QUERY PLAN rows into a tree structure."""
    nodes = []
    node_map = {}
    
    for row in explain_rows:
        node_id = row[0] if isinstance(row, tuple) else row.get('id')
        parent_id = row[1] if isinstance(row, tuple) else row.get('parent')
        detail = row[3] if isinstance(row, tuple) else row.get('detail')
        
        parent_id_str = str(parent_id) if (parent_id is not None and parent_id != 0) else None
        
        node = {
            'id': str(node_id),
            'parentId': parent_id_str,
            'detail': detail,
            'tableName': None,
            'indexName': None,
            'estimatedRows': None,
            'isFullScan': False,
            'children': []
        }
        
        if detail:
            table_match = re.search(r'SCAN (?:TABLE )?([a-zA-Z_][a-zA-Z0-9_]*)', detail, re.IGNORECASE)
            if table_match:
                node['tableName'] = table_match.group(1)
                node['isFullScan'] = 'USING INDEX' not in detail.upper()
            
            search_match = re.search(r'SEARCH (?:TABLE )?([a-zA-Z_][a-zA-Z0-9_]*)', detail, re.IGNORECASE)
            if search_match:
                node['tableName'] = search_match.group(1)
            
            index_match = re.search(r'USING (?:INDEX|COVERING INDEX) ([a-zA-Z_][a-zA-Z0-9_]*)', detail, re.IGNORECASE)
            if index_match:
                node['indexName'] = index_match.group(1)
                node['isFullScan'] = False
            
            rows_match = re.search(r'~(\d+) rows', detail)
            if rows_match:
                node['estimatedRows'] = int(rows_match.group(1))
        
        nodes.append(node)
        node_map[node['id']] = node
    
    for node in nodes:
        if node['parentId'] is not None and node['parentId'] in node_map:
            node_map[node['parentId']]['children'].append(node)
    
    roots = [node for node in nodes if node['parentId'] is None]
    
    edges = []
    for node in nodes:
        if node['parentId'] is not None:
            edges.append({
                'id': f"{node['parentId']}-{node['id']}",
                'source': node['parentId'],
                'target': node['id'],
            })
    
    return {'nodes': nodes, 'edges': edges, 'roots': roots}

def parse_explain_bytecode(bytecode_rows):
    """Parse EXPLAIN bytecode rows into a structured format."""
    result = []
    for row in bytecode_rows:
        if isinstance(row, tuple):
            result.append({
                'addr': row[0],
                'opcode': row[1],
                'p1': row[2],
                'p2': row[3],
                'p3': row[4],
                'p4': row[5] if len(row) > 5 else None,
                'p5': row[6] if len(row) > 6 else None,
                'comment': row[7] if len(row) > 7 else None,
            })
        else:
            result.append(row)
    return result

def generate_export_sql(query_name, created_at, query_structure, sql, params):
    """Generate a complete SQL export file content."""
    import json
    query_json = json.dumps(query_structure, indent=2)
    literal_sql = replace_params_in_sql(sql, params)
    
    export_content = f"""-- =====================================================
-- Query Export
-- =====================================================
-- Name: {query_name}
-- Created At: {created_at}
-- 
-- Original Query Structure:
{add_comment_prefix(query_json, '-- ')}
-- =====================================================

{literal_sql}
"""
    return export_content

def add_comment_prefix(text, prefix):
    """Add comment prefix to each line of text."""
    lines = text.split('\n')
    return '\n'.join([prefix + line for line in lines])
