import sys
sys.path.insert(0, '/Users/huwenjie/my project/solo/gen-372/backend')

import os
import json
from sqlalchemy import create_engine, text
from app import create_app
from app.services.sql_generator import SQLGenerator
from app.services.query_executor import QueryExecutor

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend', 'instance', 'sakila.db')

app = create_app()

def run_sql(sql, params=None):
    engine = create_engine(f'sqlite:///{DB_PATH}')
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [list(row) for row in result.fetchall()]

def test_acceptance_1_join_auto_detect():
    print("=" * 70)
    print("验收标准 1: customer + order JOIN")
    print("=" * 70)
    
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
        "where": None,
        "aggregations": [],
        "limit": 10
    }
    
    result = QueryExecutor.generate_sql(query)
    
    print("\n✓ SQL 生成成功:")
    print("-" * 70)
    print(result['sql'])
    print("-" * 70)
    
    assert 'INNER JOIN' in result['sql'], "SQL 中缺少 INNER JOIN"
    assert '"c"."id" = "o"."customer_id"' in result['sql'], "JOIN 条件不正确"
    
    exec_result = QueryExecutor.execute(query)
    print(f"\n✓ 查询执行成功! 返回 {exec_result['rowCount']} 行, 耗时 {exec_result['executionTime']} ms")
    
    print("\n✓ 验收标准 1 通过!")
    return True

def test_acceptance_2_where_nested():
    print("\n" + "=" * 70)
    print("验收标准 2: 嵌套 WHERE 条件 (AND/OR)")
    print("=" * 70)
    
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
    
    result = QueryExecutor.generate_sql(query)
    
    print("\n✓ SQL 生成成功:")
    print("-" * 70)
    print(result['sql'])
    print("-" * 70)
    print(f"\n参数: {json.dumps(result['params'], indent=2)}")
    
    assert 'WHERE' in result['sql'], "SQL 中缺少 WHERE"
    assert 'AND' in result['sql'], "SQL 中缺少 AND"
    assert 'OR' in result['sql'], "SQL 中缺少 OR"
    
    exec_result = QueryExecutor.execute(query)
    print(f"\n✓ 查询执行成功! 返回 {exec_result['rowCount']} 行")
    
    for row in exec_result['rows'][:5]:
        country = row[1]
        amount = row[2]
        assert country in ('US', 'UK'), f"country 应该是 US 或 UK，实际是 {country}"
        assert amount > 100, f"total_amount 应该 > 100，实际是 {amount}"
    
    handwritten_sql = """
        SELECT c.first_name, c.country, o.total_amount
        FROM customer c
        INNER JOIN "order" o ON c.id = o.customer_id
        WHERE o.total_amount > 100 AND (c.country = 'US' OR c.country = 'UK')
        LIMIT 100
    """
    
    handwritten_result = run_sql(handwritten_sql)
    print(f"\n✓ 结果对比: 可视化={exec_result['rowCount']} 行, 手写={len(handwritten_result)} 行")
    assert exec_result['rowCount'] == len(handwritten_result), "结果行数不一致"
    
    visual_set = set(tuple(r) for r in exec_result['rows'])
    hand_set = set(tuple(r) for r in handwritten_result)
    assert visual_set == hand_set, "结果数据不一致"
    
    print("\n✓ 验收标准 2 通过!")
    return True

def test_acceptance_3_aggregation():
    print("\n" + "=" * 70)
    print("验收标准 3: SUM 聚合 + GROUP BY")
    print("=" * 70)
    
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
        "where": None,
        "aggregations": [
            {"tableId": "node-2", "columnName": "total_amount", "function": "SUM", "alias": "total_spent"}
        ],
        "limit": 100
    }
    
    result = QueryExecutor.generate_sql(query)
    
    print("\n✓ SQL 生成成功:")
    print("-" * 70)
    print(result['sql'])
    print("-" * 70)
    
    assert 'SUM' in result['sql'], "SQL 中缺少 SUM 聚合"
    assert 'GROUP BY' in result['sql'], "SQL 中缺少 GROUP BY"
    
    exec_result = QueryExecutor.execute(query)
    print(f"\n✓ 查询执行成功! 返回 {exec_result['rowCount']} 行")
    
    print(f"\n✓ 结果数据:")
    visual_dict = {}
    for row in exec_result['rows']:
        visual_dict[row[0]] = round(float(row[1]), 2)
        print(f"  {row[0]}: {row[1]:.2f}")
    
    handwritten_sql = """
        SELECT c.country, SUM(o.total_amount) as total_spent
        FROM customer c
        INNER JOIN "order" o ON c.id = o.customer_id
        GROUP BY c.country
    """
    
    handwritten_result = run_sql(handwritten_sql)
    hand_dict = {row[0]: round(float(row[1]), 2) for row in handwritten_result}
    
    for country in visual_dict:
        assert abs(visual_dict[country] - hand_dict.get(country, 0)) < 0.01, f"{country} 的 SUM 结果不一致"
    
    print("\n✓ 验收标准 3 通过!")
    return True

def test_right_join_result_set():
    print("\n" + "=" * 70)
    print("验证 RIGHT JOIN 结果集与真实语义一致")
    print("=" * 70)
    
    query = {
        "tables": [
            {"id": "node-1", "tableName": "customer", "alias": "c"},
            {"id": "node-2", "tableName": "order", "alias": "o"}
        ],
        "joins": [
            {"id": "join-1", "type": "RIGHT", "leftTableId": "node-1", "leftColumn": "id", 
             "rightTableId": "node-2", "rightColumn": "customer_id", 
             "leftTable": "customer", "rightTable": "order"}
        ],
        "selectedFields": [
            {"tableId": "node-1", "columnName": "id"},
            {"tableId": "node-2", "columnName": "id"}
        ],
        "where": None,
        "aggregations": [],
        "limit": 1000
    }
    
    gen = SQLGenerator(query)
    generated_sql = gen.generate()
    params = gen.get_params()
    
    print("\n生成的 SQL:")
    print("-" * 60)
    print(generated_sql)
    print("-" * 60)
    
    print("\nRIGHT JOIN 语义验证:")
    print("  - RIGHT JOIN 应该返回所有右表(order)的行")
    print("  - 生成的 SQL 应该以 order 为驱动表")
    assert 'FROM "order" "o"' in generated_sql, "RIGHT JOIN 应该以右表为驱动表"
    assert 'LEFT JOIN "customer"' in generated_sql, "RIGHT JOIN 应该转换为 LEFT JOIN"
    
    generated_result = run_sql(generated_sql, params)
    
    handwritten_sql = """
        SELECT c.id, o.id
        FROM "order" o
        LEFT JOIN customer c ON o.customer_id = c.id
        LIMIT 1000
    """
    expected_result = run_sql(handwritten_sql)
    
    print(f"\n✓ 结果对比:")
    print(f"  生成 SQL: {len(generated_result)} 行")
    print(f"  预期 SQL: {len(expected_result)} 行")
    
    generated_set = set(tuple(r) for r in generated_result)
    expected_set = set(tuple(r) for r in expected_result)
    
    if generated_set == expected_set:
        print("\n✓ RIGHT JOIN 结果集与真实语义一致!")
        return True
    else:
        print("\n✗ RIGHT JOIN 结果集与真实语义不一致!")
        return False

def test_full_join_result_set():
    print("\n" + "=" * 70)
    print("验证 FULL JOIN 结果集与真实语义一致")
    print("=" * 70)
    
    query = {
        "tables": [
            {"id": "node-1", "tableName": "customer", "alias": "c"},
            {"id": "node-2", "tableName": "order", "alias": "o"}
        ],
        "joins": [
            {"id": "join-1", "type": "FULL", "leftTableId": "node-1", "leftColumn": "id", 
             "rightTableId": "node-2", "rightColumn": "customer_id", 
             "leftTable": "customer", "rightTable": "order"}
        ],
        "selectedFields": [
            {"tableId": "node-1", "columnName": "id"},
            {"tableId": "node-2", "columnName": "id"}
        ],
        "where": None,
        "aggregations": [],
        "limit": 1000
    }
    
    gen = SQLGenerator(query)
    generated_sql = gen.generate()
    params = gen.get_params()
    
    print("\n生成的 SQL:")
    print("-" * 60)
    print(generated_sql)
    print("-" * 60)
    
    print("\nFULL JOIN 语义验证:")
    print("  - FULL JOIN 应该返回左右两表的所有行")
    print("  - SQLite 不支持 FULL JOIN，应该用 UNION 模拟")
    assert 'UNION' in generated_sql, "FULL JOIN 应该用 UNION 模拟"
    
    generated_result = run_sql(generated_sql, params)
    
    handwritten_sql = """
        SELECT c.id, o.id
        FROM customer c
        LEFT JOIN "order" o ON c.id = o.customer_id
        UNION
        SELECT c.id, o.id
        FROM "order" o
        LEFT JOIN customer c ON o.customer_id = c.id
        LIMIT 1000
    """
    expected_result = run_sql(handwritten_sql)
    
    print(f"\n✓ 结果对比:")
    print(f"  生成 SQL: {len(generated_result)} 行")
    print(f"  预期 SQL: {len(expected_result)} 行")
    
    generated_set = set(tuple(r) for r in generated_result)
    expected_set = set(tuple(r) for r in expected_result)
    
    if generated_set == expected_set:
        print("\n✓ FULL JOIN 结果集与真实语义一致!")
        return True
    else:
        print("\n✗ FULL JOIN 结果集与真实语义不一致!")
        return False

if __name__ == '__main__':
    all_passed = True
    
    try:
        with app.app_context():
            all_passed &= test_acceptance_1_join_auto_detect()
            all_passed &= test_acceptance_2_where_nested()
            all_passed &= test_acceptance_3_aggregation()
            all_passed &= test_right_join_result_set()
            all_passed &= test_full_join_result_set()
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✓ 所有验收标准通过!")
    else:
        print("✗ 部分验收标准未通过!")
    print("=" * 70)
