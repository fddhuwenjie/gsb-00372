from app import create_app
from app.database import db
from app.models import Order, Customer
from sqlalchemy import func

app = create_app()
with app.app_context():
    orders = db.session.query(Order).all()
    print(f'Total orders: {len(orders)}')
    for o in orders[:10]:
        print(f'  Order {o.id}: customer_id={o.customer_id}, total_amount={o.total_amount}')
    
    customers = db.session.query(Customer).all()
    print(f'\nTotal customers: {len(customers)}')
    for c in customers:
        print(f'  Customer {c.id}: {c.first_name} {c.last_name}, country={c.country}')
    
    count = db.session.query(func.count(Order.id)).filter(Order.total_amount > 100).scalar()
    print(f'\nOrders with total_amount > 100: {count}')
    
    us_uk_customers = db.session.query(Customer).filter(Customer.country.in_(['US', 'UK'])).all()
    print(f'\nUS/UK customers: {len(us_uk_customers)}')
    for c in us_uk_customers:
        print(f'  {c.first_name} {c.last_name}: {c.country}')
    
    # 检查 US/UK 客户的订单 > 100
    from app.models import Order
    result = db.session.query(
        Customer.first_name,
        Customer.country,
        Order.total_amount
    ).join(Order, Customer.id == Order.customer_id
    ).filter(
        Order.total_amount > 100,
        Customer.country.in_(['US', 'UK'])
    ).all()
    
    print(f'\n符合条件的记录 (amount > 100 AND country IN (US, UK)): {len(result)}')
    for r in result:
        print(f'  {r}')
