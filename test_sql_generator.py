import sys
sys.path.insert(0, '/Users/huwenjie/my project/solo/gen-372/backend')

from app.services.sql_generator import SQLGenerator

print('SQLGenerator 导入成功\n')

query = {
    'tables': [
        {'id': 'node-1', 'tableName': 'customer', 'alias': 'c'},
        {'id': 'node-2', 'tableName': 'order', 'alias': 'o'}
    ],
    'joins': [
        {'id': 'join-1', 'type': 'LEFT', 'leftTableId': 'node-1', 'leftColumn': 'id', 
         'rightTableId': 'node-2', 'rightColumn': 'customer_id', 
         'leftTable': 'customer', 'rightTable': 'order'}
    ],
    'selectedFields': [
        {'tableId': 'node-1', 'columnName': 'first_name'},
        {'tableId': 'node-2', 'columnName': 'total_amount'}
    ],
    'where': None,
    'aggregations': [],
    'limit': 10
}

gen = SQLGenerator(query)
sql = gen.generate()
print('=' * 60)
print('LEFT JOIN SQL:')
print('=' * 60)
print(sql)
print()

query['joins'][0]['type'] = 'RIGHT'
gen = SQLGenerator(query)
sql = gen.generate()
print('=' * 60)
print('RIGHT JOIN SQL:')
print('=' * 60)
print(sql)
print()

query['joins'][0]['type'] = 'FULL'
gen = SQLGenerator(query)
sql = gen.generate()
print('=' * 60)
print('FULL JOIN SQL:')
print('=' * 60)
print(sql)
print()

query['joins'][0]['type'] = 'INNER'
gen = SQLGenerator(query)
sql = gen.generate()
print('=' * 60)
print('INNER JOIN SQL:')
print('=' * 60)
print(sql)
