import requests
import json
import os
from sqlalchemy import create_engine, text

BASE_URL = 'http://127.0.0.1:5001'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend', 'instance', 'sakila.db')

def get_db_conn():
    engine = create_engine(f'sqlite:///{DB_PATH}')
    return engine.connect()

def test_right_join():
    print("=" * 70)
    print("测试 RIGHT JOIN 正确性验证")
    print("=" * 70)
    
    query = {
        "tables": [
            {"id": "node-1", "tableName": "customer", "alias": "c", "position": {"x": 100, "y": 100}},
            {"id": "node-2", "tableName": "order", "alias": "o", "position": {"x": 400, "y": 100}}
        ],
        "joins": [
            {"id": "join-1", "type": "RIGHT", "leftTableId": "node-1", "leftColumn": "id", 
             "rightTableId": "node-2", "rightColumn": "customer_id", 
             "leftTable": "customer", "rightTable": "order"}
        ],
        "selectedFields": [
            {"tableId": "node-1", "columnName": "first_name"},
            {"tableId": "node-2", "columnName": "total_amount"}
        ],
        "where": None,
        "aggregations": [],
        "limit": 100
    }
    
    response = requests.post(f'{BASE_URL}/api/generate-sql', json=query)
    result = response.json()
    
    print("\n生成的 SQL:")
    print("-" * 70)
    print(result['sql'])
    print("-" * 70)
    
    print(f"\n参数: {json.dumps(result['params'], indent=2)}")
    
    handwritten_sql = """
        SELECT c.first_name, o.total_amount
        FROM "order" o
        LEFT JOIN customer c ON c.id = o.customer_id
        LIMIT 100
    """
    
    conn = get_db_conn()
    
    try:
        visual_result = conn.execute(text(result['sql']), result['params']).fetchall()
        hand_result = conn.execute(text(handwritten_sql)).fetchall()
        
        print(f"\n✓ 结果对比:")
        print(f"  可视化构建结果: {len(visual_result)} 行")
        print(f"  手写 SQL 结果: {len(hand_result)} 行")
        
        visual_set = set(tuple(r) for r in visual_result)
        hand_set = set(tuple(r) for r in hand_result)
        
        if visual_set == hand_set:
            print("\n✓ RIGHT JOIN 结果正确!")
            return True
        else:
            print(f"\n✗ RIGHT JOIN 结果不正确!")
            print(f"  可视化独有: {visual_set - hand_set}")
            print(f"  手写独有: {hand_set - visual_set}")
            return False
    finally:
        conn.close()

def test_full_join():
    print("\n" + "=" * 70)
    print("测试 FULL JOIN 正确性验证")
    print("=" * 70)
    
    query = {
        "tables": [
            {"id": "node-1", "tableName": "customer", "alias": "c", "position": {"x": 100, "y": 100}},
            {"id": "node-2", "tableName": "order", "alias": "o", "position": {"x": 400, "y": 100}}
        ],
        "joins": [
            {"id": "join-1", "type": "FULL", "leftTableId": "node-1", "leftColumn": "id", 
             "rightTableId": "node-2", "rightColumn": "customer_id", 
             "leftTable": "customer", "rightTable": "order"}
        ],
        "selectedFields": [
            {"tableId": "node-1", "columnName": "first_name"},
            {"tableId": "node-2", "columnName": "total_amount"}
        ],
        "where": None,
        "aggregations": [],
        "limit": 200
    }
    
    response = requests.post(f'{BASE_URL}/api/generate-sql', json=query)
    result = response.json()
    
    print("\n生成的 SQL:")
    print("-" * 70)
    print(result['sql'])
    print("-" * 70)
    
    handwritten_sql = """
        SELECT c.first_name, o.total_amount
        FROM customer c
        LEFT JOIN "order" o ON c.id = o.customer_id
        UNION
        SELECT c.first_name, o.total_amount
        FROM "order" o
        LEFT JOIN customer c ON c.id = o.customer_id
        LIMIT 200
    """
    
    conn = get_db_conn()
    
    try:
        visual_result = conn.execute(text(result['sql']), result['params']).fetchall()
        hand_result = conn.execute(text(handwritten_sql)).fetchall()
        
        print(f"\n✓ 结果对比:")
        print(f"  可视化构建结果: {len(visual_result)} 行")
        print(f"  手写 SQL 结果: {len(hand_result)} 行")
        
        visual_set = set(tuple(r) for r in visual_result)
        hand_set = set(tuple(r) for r in hand_result)
        
        if visual_set == hand_set:
            print("\n✓ FULL JOIN 结果正确!")
            return True
        else:
            print(f"\n✗ FULL JOIN 结果不正确!")
            print(f"  可视化独有: {visual_set - hand_set}")
            print(f"  手写独有: {hand_set - visual_set}")
            return False
    finally:
        conn.close()

def test_left_join_still_works():
    print("\n" + "=" * 70)
    print("测试 LEFT JOIN 仍然正常工作")
    print("=" * 70)
    
    query = {
        "tables": [
            {"id": "node-1", "tableName": "customer", "alias": "c", "position": {"x": 100, "y": 100}},
            {"id": "node-2", "tableName": "order", "alias": "o", "position": {"x": 400, "y": 100}}
        ],
        "joins": [
            {"id": "join-1", "type": "LEFT", "leftTableId": "node-1", "leftColumn": "id", 
             "rightTableId": "node-2", "rightColumn": "customer_id", 
             "leftTable": "customer", "rightTable": "order"}
        ],
        "selectedFields": [
            {"tableId": "node-1", "columnName": "first_name"},
            {"tableId": "node-2", "columnName": "total_amount"}
        ],
        "where": None,
        "aggregations": [],
        "limit": 100
    }
    
    response = requests.post(f'{BASE_URL}/api/generate-sql', json=query)
    result = response.json()
    
    print("\n生成的 SQL:")
    print("-" * 70)
    print(result['sql'])
    print("-" * 70)
    
    assert 'LEFT JOIN' in result['sql'], "SQL 中应该包含 LEFT JOIN"
    assert 'RIGHT' not in result['sql'], "SQL 中不应该包含 RIGHT"
    
    print("\n✓ LEFT JOIN 正常工作!")
    return True

if __name__ == '__main__':
    all_passed = True
    
    try:
        all_passed &= test_left_join_still_works()
        all_passed &= test_right_join()
        all_passed &= test_full_join()
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✓ 所有 JOIN 类型测试通过!")
    else:
        print("✗ 部分测试未通过!")
    print("=" * 70)
