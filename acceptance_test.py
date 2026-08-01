import requests
import json
import os

BASE_URL = 'http://127.0.0.1:5001'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend', 'instance', 'sakila.db')

def test_acceptance_1_join_auto_detect():
    """
    验收标准 1: 拖入 customer + order，自动识别外键并提示 JOIN
    """
    print("=" * 70)
    print("验收标准 1: 拖入 customer + order，自动识别外键并提示 JOIN")
    print("=" * 70)
    
    # 1. 获取元数据，检查外键关系
    response = requests.get(f'{BASE_URL}/api/metadata')
    metadata = response.json()
    
    order_table = next(t for t in metadata if t['name'] == 'order')
    print(f"\n✓ order 表有 {len(order_table['foreignKeys'])} 个外键:")
    for fk in order_table['foreignKeys']:
        print(f"  - {fk['fromColumn']} -> {fk['toTable']}.{fk['toColumn']}")
    
    customer_to_order_fk = next(
        (fk for fk in order_table['foreignKeys'] if fk['toTable'] == 'customer'),
        None
    )
    
    assert customer_to_order_fk is not None, "order.customer_id -> customer.id 外键不存在"
    print(f"\n✓ 检测到外键关系: order.{customer_to_order_fk['fromColumn']} -> customer.{customer_to_order_fk['toColumn']}")
    
    # 2. 测试包含 JOIN 的 SQL 生成
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
    
    response = requests.post(f'{BASE_URL}/api/generate-sql', json=query)
    result = response.json()
    
    print("\n✓ SQL 生成成功:")
    print("-" * 70)
    print(result['sql'])
    print("-" * 70)
    
    assert 'INNER JOIN' in result['sql'], "SQL 中缺少 INNER JOIN"
    assert '"c"."id" = "o"."customer_id"' in result['sql'], "JOIN 条件不正确"
    
    print("\n✓ 验收标准 1 通过!")
    return True

def test_acceptance_2_where_nested():
    """
    验收标准 2: 添加 WHERE order.total_amount > 100 AND (customer.country='US' OR customer.country='UK')
    """
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
    
    # 1. 测试 SQL 生成
    response = requests.post(f'{BASE_URL}/api/generate-sql', json=query)
    result = response.json()
    
    print("\n✓ SQL 生成成功:")
    print("-" * 70)
    print(result['sql'])
    print("-" * 70)
    print(f"\n参数: {json.dumps(result['params'], indent=2)}")
    
    # 验证 SQL 结构
    assert 'WHERE' in result['sql'], "SQL 中缺少 WHERE"
    assert 'AND' in result['sql'], "SQL 中缺少 AND"
    assert 'OR' in result['sql'], "SQL 中缺少 OR"
    assert result['params']['p1'] == 100, "参数 p1 不正确"
    assert result['params']['p2'] == 'US', "参数 p2 不正确"
    assert result['params']['p3'] == 'UK', "参数 p3 不正确"
    
    # 2. 执行查询并验证结果
    response = requests.post(f'{BASE_URL}/api/execute-query', json=query)
    exec_result = response.json()
    
    print(f"\n✓ 查询执行成功!")
    print(f"  执行时间: {exec_result.get('executionTime', 0)} ms")
    print(f"  返回行数: {exec_result.get('rowCount', 0)}")
    
    # 验证列类型
    print(f"\n✓ 列信息:")
    for col in exec_result.get('columns', []):
        print(f"  - {col['name']}: {col['type']}")
    
    # 验证所有结果符合条件
    print(f"\n✓ 验证结果数据:")
    for row in exec_result.get('rows', [])[:5]:
        country = row[1]
        amount = row[2]
        assert country in ('US', 'UK'), f"country 应该是 US 或 UK，实际是 {country}"
        assert amount > 100, f"total_amount 应该 > 100，实际是 {amount}"
        print(f"  {row} - ✓ 符合条件")
    
    # 3. 与手写 SQL 结果对比
    handwritten_sql = """
        SELECT c.first_name, c.country, o.total_amount
        FROM customer c
        INNER JOIN "order" o ON c.id = o.customer_id
        WHERE o.total_amount > 100 AND (c.country = 'US' OR c.country = 'UK')
        LIMIT 100
    """
    
    # 用参数化执行手写 SQL 验证结果一致性
    from sqlalchemy import create_engine, text
    engine = create_engine(f'sqlite:///{DB_PATH}')
    with engine.connect() as conn:
        handwritten_result = conn.execute(text(handwritten_sql)).fetchall()
    
    print(f"\n✓ 结果对比:")
    print(f"  可视化构建结果: {exec_result.get('rowCount', 0)} 行")
    print(f"  手写 SQL 结果: {len(handwritten_result)} 行")
    assert exec_result.get('rowCount', 0) == len(handwritten_result), "结果行数不一致"
    
    # 验证数据一致
    for i, (visual_row, hand_row) in enumerate(zip(exec_result['rows'][:10], handwritten_result[:10])):
        visual_tuple = tuple(visual_row)
        hand_tuple = tuple(hand_row)
        assert visual_tuple == hand_tuple, f"第 {i} 行数据不一致: {visual_tuple} vs {hand_tuple}"
    
    print("\n✓ 验收标准 2 通过!")
    return True

def test_acceptance_3_aggregation():
    """
    验收标准 3: 选 SUM(total_amount) GROUP BY country，结果与手写 SQL 一致
    """
    print("\n" + "=" * 70)
    print("验收标准 3: 聚合查询 SUM + GROUP BY")
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
    
    # 1. 测试 SQL 生成
    response = requests.post(f'{BASE_URL}/api/generate-sql', json=query)
    result = response.json()
    
    print("\n✓ SQL 生成成功:")
    print("-" * 70)
    print(result['sql'])
    print("-" * 70)
    
    # 验证 SQL 结构
    assert 'SUM' in result['sql'], "SQL 中缺少 SUM 聚合"
    assert 'GROUP BY' in result['sql'], "SQL 中缺少 GROUP BY"
    assert '"c"."country"' in result['sql'], "GROUP BY 条件不正确"
    
    # 2. 执行查询
    response = requests.post(f'{BASE_URL}/api/execute-query', json=query)
    exec_result = response.json()
    
    print(f"\n✓ 查询执行成功!")
    print(f"  执行时间: {exec_result.get('executionTime', 0)} ms")
    print(f"  返回行数: {exec_result.get('rowCount', 0)}")
    
    print(f"\n✓ 结果数据:")
    for row in exec_result.get('rows', []):
        print(f"  {row[0]}: {row[1]:.2f}")
    
    # 3. 与手写 SQL 结果对比
    from sqlalchemy import create_engine, text
    engine = create_engine(f'sqlite:///{DB_PATH}')
    
    handwritten_sql = """
        SELECT c.country, SUM(o.total_amount) as total_spent
        FROM customer c
        INNER JOIN "order" o ON c.id = o.customer_id
        GROUP BY c.country
        ORDER BY total_spent DESC
    """
    
    with engine.connect() as conn:
        handwritten_result = conn.execute(text(handwritten_sql)).fetchall()
    
    print(f"\n✓ 结果对比:")
    print(f"  可视化构建结果: {exec_result.get('rowCount', 0)} 行")
    print(f"  手写 SQL 结果: {len(handwritten_result)} 行")
    
    # 验证数据一致（排序可能不同，用字典比较）
    visual_dict = {row[0]: round(float(row[1]), 2) for row in exec_result['rows']}
    hand_dict = {row[0]: round(float(row[1]), 2) for row in handwritten_result}
    
    print(f"\n✓ 详细数据对比:")
    for country in sorted(visual_dict.keys()):
        visual_val = visual_dict[country]
        hand_val = hand_dict.get(country, 0)
        match = "✓" if abs(visual_val - hand_val) < 0.01 else "✗"
        print(f"  {country}: 可视化={visual_val:.2f}, 手写={hand_val:.2f} {match}")
        assert abs(visual_val - hand_val) < 0.01, f"{country} 的 SUM 结果不一致"
    
    print("\n✓ 验收标准 3 通过!")
    return True

if __name__ == '__main__':
    all_passed = True
    
    try:
        all_passed &= test_acceptance_1_join_auto_detect()
        all_passed &= test_acceptance_2_where_nested()
        all_passed &= test_acceptance_3_aggregation()
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
