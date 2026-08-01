from app.database import db
from app.models import Category, Supplier, Product, Customer, Employee, Order, OrderItem
from datetime import date

def seed_data():
    if Category.query.first():
        return
    
    categories = [
        Category(name='Electronics', description='Electronic devices and gadgets'),
        Category(name='Clothing', description='Fashion and apparel'),
        Category(name='Books', description='Books and publications'),
        Category(name='Home', description='Home and kitchen appliances'),
        Category(name='Sports', description='Sports equipment and gear'),
    ]
    db.session.add_all(categories)
    db.session.flush()
    
    suppliers = [
        Supplier(name='TechCorp', contact_name='John Smith', country='US', phone='+1-555-0101'),
        Supplier(name='FashionHub', contact_name='Emma Wilson', country='UK', phone='+44-555-0102'),
        Supplier(name='BookWorld', contact_name='Hans Mueller', country='Germany', phone='+49-555-0103'),
        Supplier(name='HomeGoods', contact_name='Marie Dubois', country='France', phone='+33-555-0104'),
        Supplier(name='SportsPro', contact_name='Carlos Ruiz', country='Spain', phone='+34-555-0105'),
    ]
    db.session.add_all(suppliers)
    db.session.flush()
    
    products = [
        Product(name='Laptop Pro', price=1299.99, stock=50, category_id=categories[0].id, supplier_id=suppliers[0].id),
        Product(name='Wireless Mouse', price=29.99, stock=200, category_id=categories[0].id, supplier_id=suppliers[0].id),
        Product(name='USB-C Hub', price=49.99, stock=150, category_id=categories[0].id, supplier_id=suppliers[0].id),
        Product(name='T-Shirt Cotton', price=19.99, stock=500, category_id=categories[1].id, supplier_id=suppliers[1].id),
        Product(name='Denim Jeans', price=59.99, stock=300, category_id=categories[1].id, supplier_id=suppliers[1].id),
        Product(name='Winter Jacket', price=129.99, stock=150, category_id=categories[1].id, supplier_id=suppliers[1].id),
        Product(name='Python Programming', price=44.99, stock=100, category_id=categories[2].id, supplier_id=suppliers[2].id),
        Product(name='Data Science Handbook', price=59.99, stock=80, category_id=categories[2].id, supplier_id=suppliers[2].id),
        Product(name='Coffee Maker', price=89.99, stock=120, category_id=categories[3].id, supplier_id=suppliers[3].id),
        Product(name='Blender', price=69.99, stock=100, category_id=categories[3].id, supplier_id=suppliers[3].id),
        Product(name='Running Shoes', price=89.99, stock=200, category_id=categories[4].id, supplier_id=suppliers[4].id),
        Product(name='Yoga Mat', price=34.99, stock=250, category_id=categories[4].id, supplier_id=suppliers[4].id),
        Product(name='Smart Watch', price=299.99, stock=75, category_id=categories[0].id, supplier_id=suppliers[0].id),
        Product(name='Bluetooth Speaker', price=79.99, stock=180, category_id=categories[0].id, supplier_id=suppliers[0].id),
    ]
    db.session.add_all(products)
    db.session.flush()
    
    customers = [
        Customer(first_name='Alice', last_name='Johnson', email='alice@example.com', country='US', city='New York'),
        Customer(first_name='Bob', last_name='Brown', email='bob@example.com', country='US', city='Los Angeles'),
        Customer(first_name='Charlie', last_name='Davis', email='charlie@example.com', country='UK', city='London'),
        Customer(first_name='Diana', last_name='Evans', email='diana@example.com', country='UK', city='Manchester'),
        Customer(first_name='Erik', last_name='Fischer', email='erik@example.com', country='Germany', city='Berlin'),
        Customer(first_name='Franz', last_name='Hoffmann', email='franz@example.com', country='Germany', city='Munich'),
        Customer(first_name='Sophie', last_name='Martin', email='sophie@example.com', country='France', city='Paris'),
        Customer(first_name='Pierre', last_name='Bernard', email='pierre@example.com', country='France', city='Lyon'),
        Customer(first_name='James', last_name='Wilson', email='james@example.com', country='US', city='Chicago'),
        Customer(first_name='Maria', last_name='Garcia', email='maria@example.com', country='Spain', city='Madrid'),
    ]
    db.session.add_all(customers)
    db.session.flush()
    
    employees = [
        Employee(first_name='Michael', last_name='Scott', position='Manager', department='Sales', hire_date=date(2020, 1, 15)),
        Employee(first_name='Pam', last_name='Beesly', position='Receptionist', department='Administration', hire_date=date(2020, 3, 20)),
        Employee(first_name='Dwight', last_name='Schrute', position='Sales Representative', department='Sales', hire_date=date(2020, 2, 10)),
        Employee(first_name='Jim', last_name='Halpert', position='Sales Representative', department='Sales', hire_date=date(2020, 4, 1)),
        Employee(first_name='Angela', last_name='Martin', position='Accountant', department='Finance', hire_date=date(2019, 6, 15)),
    ]
    db.session.add_all(employees)
    db.session.flush()
    
    orders_data = [
        (customers[0].id, employees[0].id, date(2025, 1, 15), 'completed', [(products[0].id, 1, 1299.99), (products[1].id, 2, 29.99)]),
        (customers[1].id, employees[2].id, date(2025, 1, 20), 'shipped', [(products[3].id, 3, 19.99), (products[4].id, 1, 59.99)]),
        (customers[2].id, employees[3].id, date(2025, 2, 5), 'completed', [(products[6].id, 1, 44.99), (products[7].id, 1, 59.99)]),
        (customers[3].id, employees[2].id, date(2025, 2, 10), 'pending', [(products[8].id, 1, 89.99)]),
        (customers[4].id, employees[0].id, date(2025, 2, 15), 'completed', [(products[10].id, 2, 89.99), (products[11].id, 1, 34.99)]),
        (customers[5].id, employees[3].id, date(2025, 2, 20), 'shipped', [(products[12].id, 1, 299.99)]),
        (customers[0].id, employees[2].id, date(2025, 3, 1), 'completed', [(products[2].id, 2, 49.99), (products[13].id, 1, 79.99)]),
        (customers[6].id, employees[0].id, date(2025, 3, 5), 'completed', [(products[5].id, 1, 129.99)]),
        (customers[7].id, employees[3].id, date(2025, 3, 10), 'pending', [(products[9].id, 1, 69.99), (products[8].id, 1, 89.99)]),
        (customers[8].id, employees[2].id, date(2025, 3, 15), 'shipped', [(products[0].id, 1, 1299.99)]),
        (customers[9].id, employees[0].id, date(2025, 3, 20), 'completed', [(products[10].id, 1, 89.99)]),
        (customers[1].id, employees[3].id, date(2025, 4, 1), 'completed', [(products[3].id, 5, 19.99)]),
        (customers[2].id, employees[2].id, date(2025, 4, 5), 'pending', [(products[6].id, 2, 44.99)]),
        (customers[4].id, employees[0].id, date(2025, 4, 10), 'completed', [(products[12].id, 1, 299.99), (products[13].id, 2, 79.99)]),
        (customers[6].id, employees[3].id, date(2025, 4, 15), 'shipped', [(products[11].id, 3, 34.99)]),
        (customers[8].id, employees[2].id, date(2025, 5, 1), 'completed', [(products[4].id, 2, 59.99), (products[5].id, 1, 129.99)]),
        (customers[0].id, employees[0].id, date(2025, 5, 5), 'completed', [(products[0].id, 1, 1299.99), (products[1].id, 1, 29.99), (products[2].id, 1, 49.99)]),
        (customers[3].id, employees[3].id, date(2025, 5, 10), 'pending', [(products[9].id, 2, 69.99)]),
        (customers[5].id, employees[2].id, date(2025, 5, 15), 'shipped', [(products[7].id, 1, 59.99)]),
        (customers[7].id, employees[0].id, date(2025, 5, 20), 'completed', [(products[10].id, 1, 89.99), (products[11].id, 2, 34.99)]),
    ]
    
    for cust_id, emp_id, ord_date, status, items in orders_data:
        total = sum(qty * price for _, qty, price in items)
        order = Order(
            customer_id=cust_id,
            employee_id=emp_id,
            order_date=ord_date,
            total_amount=total,
            status=status
        )
        db.session.add(order)
        db.session.flush()
        
        for prod_id, qty, price in items:
            db.session.add(OrderItem(
                order_id=order.id,
                product_id=prod_id,
                quantity=qty,
                unit_price=price
            ))
    
    db.session.commit()
