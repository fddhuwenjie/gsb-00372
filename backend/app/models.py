from app.database import db
from datetime import date, datetime, timedelta
import json

class Category(db.Model):
    __tablename__ = 'category'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    
    products = db.relationship('Product', backref='category', lazy=True)

class Supplier(db.Model):
    __tablename__ = 'supplier'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    contact_name = db.Column(db.String(100))
    country = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    
    products = db.relationship('Product', backref='supplier', lazy=True)

class Product(db.Model):
    __tablename__ = 'product'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, default=0)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    
    order_items = db.relationship('OrderItem', backref='product', lazy=True)

class Customer(db.Model):
    __tablename__ = 'customer'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(200), unique=True)
    country = db.Column(db.String(100))
    city = db.Column(db.String(100))
    
    orders = db.relationship('Order', backref='customer', lazy=True)

class Employee(db.Model):
    __tablename__ = 'employee'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    position = db.Column(db.String(100))
    department = db.Column(db.String(100))
    hire_date = db.Column(db.Date)
    
    orders = db.relationship('Order', backref='employee', lazy=True)

class Order(db.Model):
    __tablename__ = 'order'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    order_date = db.Column(db.Date, nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(50), default='pending')
    
    order_items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

class OrderItem(db.Model):
    __tablename__ = 'order_item'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)

class SavedQuery(db.Model):
    __tablename__ = 'saved_queries'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    query_structure = db.Column(db.JSON, nullable=False)
    chart_config = db.Column(db.JSON)
    share_token = db.Column(db.String(10), unique=True, index=True)
    share_expires_at = db.Column(db.DateTime)
    share_access_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'query_structure': self.query_structure,
            'chart_config': self.chart_config,
            'share_token': self.share_token,
            'share_expires_at': self.share_expires_at.isoformat() if self.share_expires_at else None,
            'share_access_count': self.share_access_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }

    def is_share_valid(self):
        if not self.share_token:
            return False
        if self.share_expires_at and datetime.utcnow() > self.share_expires_at:
            return False
        return True

class QueryHistory(db.Model):
    __tablename__ = 'query_history'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_session = db.Column(db.String(100), index=True)
    query_structure = db.Column(db.JSON, nullable=False)
    sql = db.Column(db.Text, nullable=False)
    params = db.Column(db.JSON)
    duration = db.Column(db.Float)
    row_count = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_session': self.user_session,
            'query_structure': self.query_structure,
            'sql': self.sql,
            'params': self.params,
            'duration': self.duration,
            'row_count': self.row_count,
            'created_at': self.created_at.isoformat(),
        }

    @staticmethod
    def prune_old_records(session_id, keep=50):
        records = QueryHistory.query.filter_by(user_session=session_id).order_by(QueryHistory.created_at.desc()).all()
        if len(records) > keep:
            for record in records[keep:]:
                db.session.delete(record)
            db.session.commit()

class QueryTemplate(db.Model):
    __tablename__ = 'query_templates'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    version = db.Column(db.Integer, nullable=False, default=1)
    query_structure = db.Column(db.JSON, nullable=False)
    parameters = db.Column(db.JSON, nullable=False, default=list)
    schema_refs = db.Column(db.JSON, nullable=False, default=list)
    share_token = db.Column(db.String(10), unique=True, index=True)
    share_expires_at = db.Column(db.DateTime)
    share_access_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'query_structure': self.query_structure,
            'parameters': self.parameters,
            'schema_refs': self.schema_refs,
            'share_token': self.share_token,
            'share_expires_at': self.share_expires_at.isoformat() if self.share_expires_at else None,
            'share_access_count': self.share_access_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }

    def is_share_valid(self):
        if not self.share_token:
            return False
        if self.share_expires_at and datetime.utcnow() > self.share_expires_at:
            return False
        return True


class PlanSnapshot(db.Model):
    __tablename__ = 'plan_snapshots'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id = db.Column(db.Integer, db.ForeignKey('query_templates.id'), nullable=True, index=True)
    template_version = db.Column(db.Integer, nullable=True)
    label = db.Column(db.String(200))
    ast_hash = db.Column(db.String(64), nullable=False, index=True)
    param_type_summary = db.Column(db.JSON, nullable=False, default=dict)
    normalized_plan = db.Column(db.JSON, nullable=False)
    plan_operations = db.Column(db.JSON, nullable=False, default=list)
    row_count = db.Column(db.Integer, nullable=False, default=0)
    duration_ms = db.Column(db.Float, nullable=False, default=0.0)
    query_structure = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'templateId': self.template_id,
            'templateVersion': self.template_version,
            'label': self.label,
            'astHash': self.ast_hash,
            'paramTypeSummary': self.param_type_summary,
            'normalizedPlan': self.normalized_plan,
            'planOperations': self.plan_operations,
            'rowCount': self.row_count,
            'durationMs': self.duration_ms,
            'createdAt': self.created_at.isoformat(),
        }


BATCH_RUN_STATUSES = ('pending', 'running', 'completed', 'cancelled', 'partially_failed')
BATCH_ITEM_STATUSES = ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'rejected')


class BatchRun(db.Model):
    __tablename__ = 'batch_runs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id = db.Column(db.Integer, db.ForeignKey('query_templates.id'), nullable=False, index=True)
    template_version = db.Column(db.Integer, nullable=False)
    idempotency_key = db.Column(db.String(128), unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    concurrency = db.Column(db.Integer, nullable=False, default=1)
    max_total_rows = db.Column(db.Integer)
    max_duration_ms = db.Column(db.Integer)
    total_items = db.Column(db.Integer, nullable=False, default=0)
    succeeded_count = db.Column(db.Integer, nullable=False, default=0)
    failed_count = db.Column(db.Integer, nullable=False, default=0)
    cancelled_count = db.Column(db.Integer, nullable=False, default=0)
    rejected_count = db.Column(db.Integer, nullable=False, default=0)
    total_rows = db.Column(db.Integer, nullable=False, default=0)
    total_duration_ms = db.Column(db.Float, nullable=False, default=0.0)
    error = db.Column(db.Text)
    label = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    items = db.relationship('BatchItem', backref='batch_run', lazy=True,
                            cascade='all, delete-orphan',
                            order_by='BatchItem.item_index')

    def to_dict(self, include_items=False):
        d = {
            'id': self.id,
            'templateId': self.template_id,
            'templateVersion': self.template_version,
            'idempotencyKey': self.idempotency_key,
            'status': self.status,
            'concurrency': self.concurrency,
            'maxTotalRows': self.max_total_rows,
            'maxDurationMs': self.max_duration_ms,
            'totalItems': self.total_items,
            'succeededCount': self.succeeded_count,
            'failedCount': self.failed_count,
            'cancelledCount': self.cancelled_count,
            'rejectedCount': self.rejected_count,
            'totalRows': self.total_rows,
            'totalDurationMs': self.total_duration_ms,
            'error': self.error,
            'label': self.label,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'startedAt': self.started_at.isoformat() if self.started_at else None,
            'completedAt': self.completed_at.isoformat() if self.completed_at else None,
        }
        if include_items:
            d['items'] = [item.to_dict() for item in self.items]
        return d


class BatchItem(db.Model):
    __tablename__ = 'batch_items'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    batch_run_id = db.Column(db.Integer, db.ForeignKey('batch_runs.id'), nullable=False, index=True)
    item_index = db.Column(db.Integer, nullable=False)
    parameter_values = db.Column(db.JSON, nullable=False)
    param_type_summary = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    result_columns = db.Column(db.JSON)
    result_rows = db.Column(db.JSON)
    row_count = db.Column(db.Integer, nullable=False, default=0)
    duration_ms = db.Column(db.Float, nullable=False, default=0.0)
    error = db.Column(db.Text)
    plan_snapshot_id = db.Column(db.Integer, db.ForeignKey('plan_snapshots.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'batchRunId': self.batch_run_id,
            'itemIndex': self.item_index,
            'parameterSummary': self.param_type_summary,
            'status': self.status,
            'attemptCount': self.attempt_count,
            'rowCount': self.row_count,
            'durationMs': self.duration_ms,
            'error': self.error,
            'planSnapshotId': self.plan_snapshot_id,
            'columns': self.result_columns,
            'rows': self.result_rows,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'startedAt': self.started_at.isoformat() if self.started_at else None,
            'completedAt': self.completed_at.isoformat() if self.completed_at else None,
        }
