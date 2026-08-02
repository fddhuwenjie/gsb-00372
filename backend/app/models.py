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
    """A reusable, parameterized query. The current definition lives on the
    row; every saved change is also captured as a TemplateVersion so older
    instantiations stay reproducible. References inside query_structure use
    stable table-instance ids, so a template keeps working across save, share
    and (compatible) schema refreshes."""
    __tablename__ = 'query_templates'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    # The query AST with $param placeholders in value-only slots.
    query_structure = db.Column(db.JSON, nullable=False)
    # Declared parameters: [{name, type, required, default, label, itemType}]
    parameters = db.Column(db.JSON, nullable=False, default=list)
    current_version = db.Column(db.Integer, nullable=False, default=1)
    share_token = db.Column(db.String(10), unique=True, index=True)
    share_expires_at = db.Column(db.DateTime)
    share_access_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = db.relationship(
        'TemplateVersion', backref='template', lazy=True,
        cascade='all, delete-orphan', order_by='TemplateVersion.version'
    )

    def to_dict(self, include_versions=False):
        data = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'query_structure': self.query_structure,
            'parameters': self.parameters or [],
            'current_version': self.current_version,
            'share_token': self.share_token,
            'share_expires_at': self.share_expires_at.isoformat() if self.share_expires_at else None,
            'share_access_count': self.share_access_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
        if include_versions:
            data['versions'] = [v.to_dict() for v in self.versions]
        return data

    def is_share_valid(self):
        if not self.share_token:
            return False
        if self.share_expires_at and datetime.utcnow() > self.share_expires_at:
            return False
        return True


class TemplateVersion(db.Model):
    """An immutable snapshot of a template definition at a point in time."""
    __tablename__ = 'template_versions'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id = db.Column(db.Integer, db.ForeignKey('query_templates.id'), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    query_structure = db.Column(db.JSON, nullable=False)
    parameters = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('template_id', 'version', name='uq_template_version'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'template_id': self.template_id,
            'version': self.version,
            'query_structure': self.query_structure,
            'parameters': self.parameters or [],
            'created_at': self.created_at.isoformat(),
        }


class ExecutionPlanRecord(db.Model):
    """A captured execution of a query: the semantic fingerprint of the AST,
    the *types* of the bound parameters (never their raw values), the
    normalized SQLite plan, and the observed cost. Used to compare the plans
    and results of two template versions without leaking sensitive inputs."""
    __tablename__ = 'execution_plan_records'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id = db.Column(db.Integer, db.ForeignKey('query_templates.id'), index=True)
    template_version = db.Column(db.Integer, index=True)
    # Stable, order-independent fingerprint of query semantics.
    ast_hash = db.Column(db.String(64), nullable=False, index=True)
    # Canonical AST used for locatable change sets.
    canonical_ast = db.Column(db.JSON, nullable=False)
    # {byName: {name: type}, histogram: {...}, count} -- types only.
    param_type_summary = db.Column(db.JSON, nullable=False, default=dict)
    # AST-keyed normalized EXPLAIN QUERY PLAN.
    normalized_plan = db.Column(db.JSON, nullable=False, default=dict)
    # Raw EXPLAIN QUERY PLAN rows (structural, no parameter values).
    raw_plan = db.Column(db.JSON)
    duration_ms = db.Column(db.Float)
    row_count = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'template_id': self.template_id,
            'template_version': self.template_version,
            'ast_hash': self.ast_hash,
            'canonical_ast': self.canonical_ast,
            'param_type_summary': self.param_type_summary,
            'normalized_plan': self.normalized_plan,
            'raw_plan': self.raw_plan,
            'duration_ms': self.duration_ms,
            'row_count': self.row_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# Terminal and in-flight states for batch runs / items.
BATCH_STATUS = ('pending', 'running', 'completed', 'cancelled', 'failed')
ITEM_STATUS = ('pending', 'running', 'succeeded', 'failed', 'rejected', 'cancelled')
ITEM_TERMINAL = ('succeeded', 'failed', 'rejected', 'cancelled')


class BatchRun(db.Model):
    """A cancellable batch execution of one *immutable* template version against
    many parameter sets. Concurrency, total row and total time budgets are
    fixed at submit time. Progress is fully recoverable from the persisted
    per-item states; nothing sensitive (raw parameter values) is stored."""
    __tablename__ = 'batch_runs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id = db.Column(db.Integer, db.ForeignKey('query_templates.id'), nullable=False, index=True)
    # The frozen version this batch runs against; never changes for this batch.
    template_version = db.Column(db.Integer, nullable=False)
    # Idempotency: a repeated submit with the same key returns the same batch.
    idempotency_key = db.Column(db.String(80), unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    max_concurrency = db.Column(db.Integer, nullable=False, default=4)
    max_total_rows = db.Column(db.Integer)          # global cap across all items
    max_total_ms = db.Column(db.Integer)            # wall-clock budget for batch
    per_item_timeout_ms = db.Column(db.Integer, nullable=False, default=5000)
    per_item_max_rows = db.Column(db.Integer, nullable=False, default=1000)
    total_rows = db.Column(db.Integer, nullable=False, default=0)
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)

    items = db.relationship(
        'BatchRunItem', backref='batch', lazy=True,
        cascade='all, delete-orphan', order_by='BatchRunItem.item_index',
    )

    def counts(self):
        c = {s: 0 for s in ITEM_STATUS}
        for it in self.items:
            c[it.status] = c.get(it.status, 0) + 1
        return c

    def to_dict(self, include_items=True):
        data = {
            'id': self.id,
            'template_id': self.template_id,
            'template_version': self.template_version,
            'idempotency_key': self.idempotency_key,
            'status': self.status,
            'max_concurrency': self.max_concurrency,
            'max_total_rows': self.max_total_rows,
            'max_total_ms': self.max_total_ms,
            'per_item_timeout_ms': self.per_item_timeout_ms,
            'per_item_max_rows': self.per_item_max_rows,
            'total_rows': self.total_rows,
            'cancel_requested': self.cancel_requested,
            'counts': self.counts(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }
        if include_items:
            data['items'] = [it.to_dict() for it in sorted(self.items, key=lambda i: i.item_index)]
        return data


class BatchRunItem(db.Model):
    """One parameter set within a batch. ``item_index`` fixes a stable order.
    Each item carries only a parameter *type* summary and a link to the
    captured execution plan record -- never the raw parameter values."""
    __tablename__ = 'batch_run_items'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch_runs.id'), nullable=False, index=True)
    item_index = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    # Type-only summary of this item's parameters (no raw values).
    param_type_summary = db.Column(db.JSON)
    plan_record_id = db.Column(db.Integer, db.ForeignKey('execution_plan_records.id'))
    row_count = db.Column(db.Integer)
    duration_ms = db.Column(db.Float)
    error = db.Column(db.Text)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('batch_id', 'item_index', name='uq_batch_item_index'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'batch_id': self.batch_id,
            'item_index': self.item_index,
            'status': self.status,
            'param_type_summary': self.param_type_summary,
            'plan_record_id': self.plan_record_id,
            'row_count': self.row_count,
            'duration_ms': self.duration_ms,
            'error': self.error,
            'attempts': self.attempts,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
