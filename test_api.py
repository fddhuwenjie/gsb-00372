import requests
import json

BASE_URL = 'http://127.0.0.1:5001'

def test_metadata():
    print("=" * 60)
    print("TEST 1: Metadata API")
    print("=" * 60)
    response = requests.get(f'{BASE_URL}/api/metadata')
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Got {len(data)} tables")
        for table in data:
            fk_count = len(table.get('foreignKeys', []))
            print(f"  - {table['name']}: {len(table['columns'])} cols, {fk_count} FKs")
            for col in table['columns'][:3]:
                pk = " [PK]" if col.get('isPrimaryKey') else ""
                print(f"      * {col['name']}: {col['type']}{pk}")
            if len(table['columns']) > 3:
                print(f"      ... and {len(table['columns']) - 3} more")
        return True
    else:
        print(f"✗ Error: {response.status_code} - {response.text}")
        return False

def test_sql_generation():
    print("\n" + "=" * 60)
    print("TEST 2: SQL Generation with JOIN and WHERE")
    print("=" * 60)
    
    query = {
        "tables": [
            {"id": "node-1", "tableName": "customer", "alias": "c", "position": {"x": 100, "y": 100}},
            {"id": "node-2", "tableName": "order", "alias": "o", "position": {"x": 400, "y": 100}}
        ],
        "joins": [
            {"id": "join-1", "type": "INNER", "leftTableId": "node-1", "leftColumn": "id", 
             "rightTableId": "node-2", "rightColumn": "customer_id", 
             "leftTable": "customer", "rightTable": "order"}
        ],
        "selectedFields": [
            {"tableId": "node-1", "columnName": "first_name"},
            {"tableId": "node-1", "columnName": "country"},
            {"tableId": "node-2", "columnName": "total_amount"}
        ],
        "where": {
            "id": "where-1",
            "op": "AND",
            "children": [
                {"id": "clause-1", "tableId": "node-2", "columnName": "total_amount", "cmp": ">", "value": 100},
                {"id": "group-1", "op": "OR", "children": [
                    {"id": "clause-2", "tableId": "node-1", "columnName": "country", "cmp": "=", "value": "US"},
                    {"id": "clause-3", "tableId": "node-1", "columnName": "country", "cmp": "=", "value": "UK"}
                ]}
            ]
        },
        "aggregations": [],
        "limit": 10
    }
    
    response = requests.post(f'{BASE_URL}/api/generate-sql', json=query)
    if response.status_code == 200:
        data = response.json()
        print("✓ SQL generated successfully!")
        print("\nGenerated SQL:")
        print("-" * 60)
        print(data['sql'])
        print("-" * 60)
        if data.get('params'):
            print(f"\nParameters: {json.dumps(data['params'], indent=2)}")
        return True
    else:
        print(f"✗ Error: {response.status_code} - {response.text}")
        return False

def test_aggregation():
    print("\n" + "=" * 60)
    print("TEST 3: SQL Generation with Aggregation")
    print("=" * 60)
    
    query = {
        "tables": [
            {"id": "node-1", "tableName": "customer", "alias": "c", "position": {"x": 100, "y": 100}},
            {"id": "node-2", "tableName": "order", "alias": "o", "position": {"x": 400, "y": 100}}
        ],
        "joins": [
            {"id": "join-1", "type": "INNER", "leftTableId": "node-1", "leftColumn": "id", 
             "rightTableId": "node-2", "rightColumn": "customer_id", 
             "leftTable": "customer", "rightTable": "order"}
        ],
        "selectedFields": [
            {"tableId": "node-1", "columnName": "country"}
        ],
        "where": {
            "id": "where-1",
            "op": "AND",
            "children": [
                {"id": "clause-1", "tableId": "node-2", "columnName": "total_amount", "cmp": ">", "value": 100},
                {"id": "group-1", "op": "OR", "children": [
                    {"id": "clause-2", "tableId": "node-1", "columnName": "country", "cmp": "=", "value": "US"},
                    {"id": "clause-3", "tableId": "node-1", "columnName": "country", "cmp": "=", "value": "UK"}
                ]}
            ]
        },
        "aggregations": [
            {"tableId": "node-2", "columnName": "total_amount", "function": "SUM", "alias": "total_spent"}
        ],
        "limit": 10
    }
    
    response = requests.post(f'{BASE_URL}/api/generate-sql', json=query)
    if response.status_code == 200:
        data = response.json()
        print("✓ Aggregation SQL generated successfully!")
        print("\nGenerated SQL:")
        print("-" * 60)
        print(data['sql'])
        print("-" * 60)
        return True
    else:
        print(f"✗ Error: {response.status_code} - {response.text}")
        return False

def test_query_execution():
    print("\n" + "=" * 60)
    print("TEST 4: Query Execution")
    print("=" * 60)
    
    query = {
        "tables": [
            {"id": "node-1", "tableName": "customer", "alias": "c", "position": {"x": 100, "y": 100}},
            {"id": "node-2", "tableName": "order", "alias": "o", "position": {"x": 400, "y": 100}}
        ],
        "joins": [
            {"id": "join-1", "type": "INNER", "leftTableId": "node-1", "leftColumn": "id", 
             "rightTableId": "node-2", "rightColumn": "customer_id", 
             "leftTable": "customer", "rightTable": "order"}
        ],
        "selectedFields": [
            {"tableId": "node-1", "columnName": "country"}
        ],
        "where": {
            "id": "where-1",
            "op": "AND",
            "children": [
                {"id": "clause-1", "tableId": "node-2", "columnName": "total_amount", "cmp": ">", "value": 100},
                {"id": "group-1", "op": "OR", "children": [
                    {"id": "clause-2", "tableId": "node-1", "columnName": "country", "cmp": "=", "value": "US"},
                    {"id": "clause-3", "tableId": "node-1", "columnName": "country", "cmp": "=", "value": "UK"}
                ]}
            ]
        },
        "aggregations": [
            {"tableId": "node-2", "columnName": "total_amount", "function": "SUM", "alias": "total_spent"}
        ],
        "limit": 10
    }
    
    response = requests.post(f'{BASE_URL}/api/execute-query', json=query)
    if response.status_code == 200:
        data = response.json()
        if 'error' in data:
            print(f"✗ Query error: {data['error']}")
            return False
            
        print("✓ Query executed successfully!")
        print(f"\nExecution time: {data.get('executionTime', 0)} ms")
        print(f"Row count: {data.get('rowCount', 0)}")
        print(f"\nSQL:")
        print("-" * 60)
        print(data.get('sql', ''))
        print("-" * 60)
        print("\nColumns:")
        for col in data.get('columns', []):
            print(f"  - {col['name']}: {col['type']}")
        print("\nFirst 5 rows:")
        for row in data.get('rows', [])[:5]:
            print(f"  {row}")
        return True
    else:
        print(f"✗ HTTP Error: {response.status_code} - {response.text}")
        return False

if __name__ == '__main__':
    all_passed = True
    all_passed &= test_metadata()
    all_passed &= test_sql_generation()
    all_passed &= test_aggregation()
    all_passed &= test_query_execution()
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED!")
    else:
        print("✗ SOME TESTS FAILED!")
    print("=" * 60)
