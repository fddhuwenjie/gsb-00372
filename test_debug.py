import requests
import json

BASE_URL = 'http://127.0.0.1:5001'

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
    "limit": 100
}

print("=" * 70)
print("DEBUG: Testing execute-query API")
print("=" * 70)

# 先生成 SQL
response = requests.post(f'{BASE_URL}/api/generate-sql', json=query)
gen_result = response.json()
print("\nGenerated SQL:")
print(gen_result['sql'])
print(f"\nParams: {json.dumps(gen_result['params'], indent=2)}")

# 再执行查询
print("\n" + "=" * 70)
print("Executing query...")
response = requests.post(f'{BASE_URL}/api/execute-query', json=query)
exec_result = response.json()

if 'error' in exec_result:
    print(f"ERROR: {exec_result['error']}")
else:
    print(f"\nRow count: {exec_result.get('rowCount', 0)}")
    print(f"Columns: {[c['name'] + '(' + c['type'] + ')' for c in exec_result.get('columns', [])]}")
    print(f"\nRows:")
    for row in exec_result.get('rows', []):
        print(f"  {row}")

# 直接用 SQLite 验证
print("\n" + "=" * 70)
print("Direct SQLite test with same SQL and params")
print("=" * 70)
import sqlite3
import os

db_path = os.path.abspath('backend/instance/sakila.db')
print(f"DB path: {db_path}")
print(f"DB exists: {os.path.exists(db_path)}")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

sql = """
SELECT "c"."first_name", "c"."country", "o"."total_amount"
FROM "customer" "c"
INNER JOIN "order" "o" ON "c"."id" = "o"."customer_id"
WHERE ("o"."total_amount" > ? AND ("c"."country" = ? OR "c"."country" = ?))
LIMIT 100
"""
params = (100, 'US', 'UK')

print(f"\nSQL: {sql}")
print(f"Params: {params}")

cursor.execute(sql, params)
rows = cursor.fetchall()
print(f"\nDirect SQLite row count: {len(rows)}")
for row in rows[:5]:
    print(f"  {row}")

conn.close()
