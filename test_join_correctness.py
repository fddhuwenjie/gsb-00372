import sys
sys.path.insert(0, '/Users/huwenjie/my project/solo/gen-372/backend')

import os
from sqlalchemy import create_engine, text
from app.services.sql_generator import SQLGenerator

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend', 'instance', 'sakila.db')
engine = create_engine(f'sqlite:///{DB_PATH}')

def run_sql(sql, params=None):
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [list(row) for row in result.fetchall()]

def test_right_join_correctness():
    print("=" * 70)
    print("测试 RIGHT JOIN 结果正确性")
    print("=" * 70)
    
    query = {
        'tables': [
            {'id': 'node-1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'node-2', 'tableName': 'order', 'alias': 'o'}
        ],
        'joins': [
            {'id': 'join-1', 'type': 'RIGHT', 'leftTableId': 'node-1', 'leftColumn': 'id', 
             'rightTableId': 'node-2', 'rightColumn': 'customer_id', 
             'leftTable': 'customer', 'rightTable': 'order'}
        ],
        'selectedFields': [
            {'tableId': 'node-1', 'columnName': 'id'},
            {'tableId': 'node-1', 'columnName': 'first_name'},
            {'tableId': 'node-2', 'columnName': 'id'},
            {'tableId': 'node-2', 'columnName': 'total_amount'}
        ],
        'where': None,
        'aggregations': [],
        'limit': 1000
    }
    
    gen = SQLGenerator(query)
    generated_sql = gen.generate()
    params = gen.get_params()
    
    print("\n生成的 SQL:")
    print("-" * 60)
    print(generated_sql)
    print("-" * 60)
    print(f"\n参数: {params}")
    
    expected_sql = """
        SELECT c.id, c.first_name, o.id, o.total_amount
        FROM "order" o
        LEFT JOIN customer c ON o.customer_id = c.id
        LIMIT 1000
    """
    
    generated_result = run_sql(generated_sql, params)
    expected_result = run_sql(expected_sql)
    
    print(f"\n✓ 结果对比:")
    print(f"  生成 SQL 结果: {len(generated_result)} 行")
    print(f"  预期 SQL 结果: {len(expected_result)} 行")
    
    generated_set = set(tuple(r) for r in generated_result)
    expected_set = set(tuple(r) for r in expected_result)
    
    if generated_set == expected_set:
        print("\n✓ RIGHT JOIN 结果正确!")
        return True
    else:
        print(f"\n✗ RIGHT JOIN 结果不正确!")
        only_generated = generated_set - expected_set
        only_expected = expected_set - generated_set
        if only_generated:
            print(f"  生成 SQL 独有: {list(only_generated)[:3]}")
        if only_expected:
            print(f"  预期 SQL 独有: {list(only_expected)[:3]}")
        return False

def test_full_join_correctness():
    print("\n" + "=" * 70)
    print("测试 FULL JOIN 结果正确性")
    print("=" * 70)
    
    query = {
        'tables': [
            {'id': 'node-1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'node-2', 'tableName': 'order', 'alias': 'o'}
        ],
        'joins': [
            {'id': 'join-1', 'type': 'FULL', 'leftTableId': 'node-1', 'leftColumn': 'id', 
             'rightTableId': 'node-2', 'rightColumn': 'customer_id', 
             'leftTable': 'customer', 'rightTable': 'order'}
        ],
        'selectedFields': [
            {'tableId': 'node-1', 'columnName': 'id'},
            {'tableId': 'node-1', 'columnName': 'first_name'},
            {'tableId': 'node-2', 'columnName': 'id'},
            {'tableId': 'node-2', 'columnName': 'total_amount'}
        ],
        'where': None,
        'aggregations': [],
        'limit': 1000
    }
    
    gen = SQLGenerator(query)
    generated_sql = gen.generate()
    params = gen.get_params()
    
    print("\n生成的 SQL:")
    print("-" * 60)
    print(generated_sql)
    print("-" * 60)
    print(f"\n参数: {params}")
    
    expected_sql = """
        SELECT c.id, c.first_name, o.id, o.total_amount
        FROM customer c
        LEFT JOIN "order" o ON c.id = o.customer_id
        UNION
        SELECT c.id, c.first_name, o.id, o.total_amount
        FROM "order" o
        LEFT JOIN customer c ON o.customer_id = c.id
        LIMIT 1000
    """
    
    generated_result = run_sql(generated_sql, params)
    expected_result = run_sql(expected_sql)
    
    print(f"\n✓ 结果对比:")
    print(f"  生成 SQL 结果: {len(generated_result)} 行")
    print(f"  预期 SQL 结果: {len(expected_result)} 行")
    
    generated_set = set(tuple(r) for r in generated_result)
    expected_set = set(tuple(r) for r in expected_result)
    
    if generated_set == expected_set:
        print("\n✓ FULL JOIN 结果正确!")
        return True
    else:
        print(f"\n✗ FULL JOIN 结果不正确!")
        only_generated = generated_set - expected_set
        only_expected = expected_set - generated_set
        if only_generated:
            print(f"  生成 SQL 独有: {list(only_generated)[:3]}")
        if only_expected:
            print(f"  预期 SQL 独有: {list(only_expected)[:3]}")
        return False

def test_inner_join_unchanged():
    print("\n" + "=" * 70)
    print("测试 INNER JOIN 没有被影响")
    print("=" * 70)
    
    query = {
        'tables': [
            {'id': 'node-1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'node-2', 'tableName': 'order', 'alias': 'o'}
        ],
        'joins': [
            {'id': 'join-1', 'type': 'INNER', 'leftTableId': 'node-1', 'leftColumn': 'id', 
             'rightTableId': 'node-2', 'rightColumn': 'customer_id', 
             'leftTable': 'customer', 'rightTable': 'order'}
        ],
        'selectedFields': [
            {'tableId': 'node-1', 'columnName': 'first_name'},
            {'tableId': 'node-2', 'columnName': 'total_amount'}
        ],
        'where': None,
        'aggregations': [],
        'limit': 100
    }
    
    gen = SQLGenerator(query)
    sql = gen.generate()
    
    print("\n生成的 SQL:")
    print("-" * 60)
    print(sql)
    print("-" * 60)
    
    assert 'INNER JOIN' in sql, "应该包含 INNER JOIN"
    assert 'LEFT' not in sql, "不应该包含 LEFT"
    assert 'RIGHT' not in sql, "不应该包含 RIGHT"
    assert 'UNION' not in sql, "不应该包含 UNION"
    
    print("\n✓ INNER JOIN 正常工作!")
    return True

def test_three_tables_right_join():
    print("\n" + "=" * 70)
    print("测试多表 RIGHT JOIN (customer, order, order_item)")
    print("=" * 70)
    
    query = {
        'tables': [
            {'id': 'node-1', 'tableName': 'customer', 'alias': 'c'},
            {'id': 'node-2', 'tableName': 'order', 'alias': 'o'},
            {'id': 'node-3', 'tableName': 'order_item', 'alias': 'oi'}
        ],
        'joins': [
            {'id': 'join-1', 'type': 'RIGHT', 'leftTableId': 'node-1', 'leftColumn': 'id', 
             'rightTableId': 'node-2', 'rightColumn': 'customer_id', 
             'leftTable': 'customer', 'rightTable': 'order'},
            {'id': 'join-2', 'type': 'LEFT', 'leftTableId': 'node-2', 'leftColumn': 'id', 
             'rightTableId': 'node-3', 'rightColumn': 'order_id', 
             'leftTable': 'order', 'rightTable': 'order_item'}
        ],
        'selectedFields': [
            {'tableId': 'node-1', 'columnName': 'first_name'},
            {'tableId': 'node-2', 'columnName': 'total_amount'},
            {'tableId': 'node-3', 'columnName': 'quantity'}
        ],
        'where': None,
        'aggregations': [],
        'limit': 100
    }
    
    gen = SQLGenerator(query)
    generated_sql = gen.generate()
    params = gen.get_params()
    
    print("\n生成的 SQL:")
    print("-" * 60)
    print(generated_sql)
    print("-" * 60)
    
    expected_sql = """
        SELECT c.first_name, o.total_amount, oi.quantity
        FROM "order" o
        LEFT JOIN customer c ON o.customer_id = c.id
        LEFT JOIN order_item oi ON o.id = oi.order_id
        LIMIT 100
    """
    
    generated_result = run_sql(generated_sql, params)
    expected_result = run_sql(expected_sql)
    
    print(f"\n✓ 结果对比:")
    print(f"  生成 SQL 结果: {len(generated_result)} 行")
    print(f"  预期 SQL 结果: {len(expected_result)} 行")
    
    generated_set = set(tuple(r) for r in generated_result)
    expected_set = set(tuple(r) for r in expected_result)
    
    if generated_set == expected_set:
        print("\n✓ 多表 RIGHT JOIN 结果正确!")
        return True
    else:
        print(f"\n✗ 多表 RIGHT JOIN 结果不正确!")
        only_generated = generated_set - expected_set
        only_expected = expected_set - generated_set
        if only_generated:
            print(f"  生成 SQL 独有: {list(only_generated)[:3]}")
        if only_expected:
            print(f"  预期 SQL 独有: {list(only_expected)[:3]}")
        return False

if __name__ == '__main__':
    all_passed = True
    
    try:
        all_passed &= test_right_join_correctness()
        all_passed &= test_full_join_correctness()
        all_passed &= test_inner_join_unchanged()
        all_passed &= test_three_tables_right_join()
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✓ 所有 JOIN 正确性测试通过!")
    else:
        print("✗ 部分测试未通过!")
    print("=" * 70)
