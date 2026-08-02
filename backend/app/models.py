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

class QueryTemplate(db.Model):
    __tablename__ = 'query_templates'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    template_version = db.Column(db.Integer, nullable=False, default=1)
    template_definition = db.Column(db.JSON, nullable=False)
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
            'template_version': self.template_version,
            'template_definition': self.template_definition,
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


class QueryExecution(db.Model):
    """
    One recorded execution of a query AST, with its plan fingerprint.

    Sensitive parameter *values* are never stored. We only keep the
    parameter type/null summary, the canonical AST hash, the parsed
    EXPLAIN QUERY PLAN, timing and row count.
    """
    __tablename__ = 'query_executions'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_session = db.Column(db.String(100), index=True)

    ast_hash = db.Column(db.String(64), index=True, nullable=False)
    ast_structure = db.Column(db.JSON, nullable=False)
    param_type_summary = db.Column(db.JSON)

    plan_fingerprint = db.Column(db.String(64), index=True)
    plan_nodes = db.Column(db.JSON)

    duration_ms = db.Column(db.Float)
    row_count = db.Column(db.Integer)
    column_count = db.Column(db.Integer)

    template_id = db.Column(db.Integer, db.ForeignKey('query_templates.id'), index=True)
    template_version = db.Column(db.Integer)

    sql_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'astHash': self.ast_hash,
            'paramTypeSummary': self.param_type_summary,
            'planFingerprint': self.plan_fingerprint,
            'planNodes': self.plan_nodes,
            'durationMs': self.duration_ms,
            'rowCount': self.row_count,
            'columnCount': self.column_count,
            'templateId': self.template_id,
            'templateVersion': self.template_version,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }


class BatchRun(db.Model):
    """
    A cancellable batch execution of one immutable template version over
    many parameter sets. State is persisted so a cancelled/failed run can
    be queried or retried without re-running successful items.
    """
    __tablename__ = 'batch_runs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    idempotency_key = db.Column(db.String(128), unique=True, index=True)
    user_session = db.Column(db.String(100), index=True)

    template_id = db.Column(
        db.Integer, db.ForeignKey('query_templates.id'), nullable=False,
    )
    template_version = db.Column(db.Integer, nullable=False)

    status = db.Column(db.String(20), nullable=False, default='pending')
    # pending -> running -> completed | cancelled | failed
    concurrency = db.Column(db.Integer, nullable=False, default=2)
    max_total_rows = db.Column(db.Integer)
    timeout_seconds = db.Column(db.Float)

    total_items = db.Column(db.Integer, nullable=False, default=0)
    succeeded_items = db.Column(db.Integer, nullable=False, default=0)
    failed_items = db.Column(db.Integer, nullable=False, default=0)
    cancelled_items = db.Column(db.Integer, nullable=False, default=0)
    total_rows = db.Column(db.Integer, nullable=False, default=0)

    error = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, index=True,
    )
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)

    items = db.relationship(
        'BatchItem', backref='batch_run',
        cascade='all, delete-orphan', lazy='dynamic',
    )

    def to_dict(self, include_items=False):
        data = {
            'id': self.id,
            'idempotencyKey': self.idempotency_key,
            'templateId': self.template_id,
            'templateVersion': self.template_version,
            'status': self.status,
            'concurrency': self.concurrency,
            'maxTotalRows': self.max_total_rows,
            'timeoutSeconds': self.timeout_seconds,
            'totalItems': self.total_items,
            'succeededItems': self.succeeded_items,
            'failedItems': self.failed_items,
            'cancelledItems': self.cancelled_items,
            'totalRows': self.total_rows,
            'error': self.error,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'startedAt': self.started_at.isoformat() if self.started_at else None,
            'finishedAt': self.finished_at.isoformat() if self.finished_at else None,
        }
        if include_items:
            data['items'] = [i.to_dict() for i in self.items.all()]
        return data


class BatchItem(db.Model):
    """
    One parameter set within a batch run. Results are stored per item so
    successful items are not re-executed on retry; each item result is
    isolated (a rejected item never pollutes the others).
    """
    __tablename__ = 'batch_items'

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    batch_id = db.Column(
        db.Integer, db.ForeignKey('batch_runs.id'),
        nullable=False, index=True,
    )
    item_index = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)

    # Non-sensitive parameter type summary only (no raw values).
    param_type_summary = db.Column(db.JSON)
    # A client-supplied label/correlation id, never used in SQL.
    label = db.Column(db.String(200))

    execution_id = db.Column(
        db.Integer, db.ForeignKey('query_executions.id'),
    )
    plan_fingerprint = db.Column(db.String(64))
    row_count = db.Column(db.Integer)
    duration_ms = db.Column(db.Float)
    error = db.Column(db.Text)
    # Only a short preview of rows is retained per item to bound storage.
    result_preview = db.Column(db.JSON)

    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint('batch_id', 'item_index', name='uq_batch_item'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'itemIndex': self.item_index,
            'status': self.status,
            'paramTypeSummary': self.param_type_summary,
            'label': self.label,
            'executionId': self.execution_id,
            'planFingerprint': self.plan_fingerprint,
            'rowCount': self.row_count,
            'durationMs': self.duration_ms,
            'error': self.error,
            'resultPreview': self.result_preview,
            'startedAt': self.started_at.isoformat() if self.started_at else None,
            'finishedAt': self.finished_at.isoformat() if self.finished_at else None,
        }
