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
    """A reusable, versioned parameterized query template.

    ``query_structure`` holds the unified AST with stable table-instance ids;
    ``parameters`` declares typed parameters whose targets point at condition
    clause ids / limit / offset inside that AST. Instantiation only replaces
    parameter *values*; the SQL structure can never be spliced.
    """
    __tablename__ = 'query_templates'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    version = db.Column(db.Integer, nullable=False, default=1)
    parameters = db.Column(db.JSON, nullable=False, default=list)
    query_structure = db.Column(db.JSON, nullable=False)
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
            'parameters': self.parameters or [],
            'query_structure': self.query_structure,
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

class TemplateVersion(db.Model):
    """Archived version of a template (AST + parameters) for plan comparison."""
    __tablename__ = 'template_versions'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id = db.Column(db.Integer, db.ForeignKey('query_templates.id'), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    parameters = db.Column(db.JSON, nullable=False, default=list)
    query_structure = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('template_id', 'version', name='uq_template_version'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'template_id': self.template_id,
            'version': self.version,
            'parameters': self.parameters or [],
            'query_structure': self.query_structure,
            'created_at': self.created_at.isoformat(),
        }

class ExecutionSnapshot(db.Model):
    """Audit record of one query execution: AST hash, parameter *type*
    summary (never raw values), normalized EXPLAIN plan, duration and row
    count."""
    __tablename__ = 'execution_snapshots'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id = db.Column(db.Integer, index=True)
    template_version = db.Column(db.Integer)
    ast_hash = db.Column(db.String(32), nullable=False, index=True)
    params_summary = db.Column(db.JSON)          # {name: type_tag}, no raw values
    plan_json = db.Column(db.JSON)               # normalized EXPLAIN QUERY PLAN
    duration_ms = db.Column(db.Float)
    row_count = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'template_id': self.template_id,
            'template_version': self.template_version,
            'ast_hash': self.ast_hash,
            'params_summary': self.params_summary or {},
            'plan_json': self.plan_json or {},
            'duration_ms': self.duration_ms,
            'row_count': self.row_count,
            'created_at': self.created_at.isoformat(),
        }

class BatchRun(db.Model):
    """One batch parameter run: an immutable template version plus N
    parameter sets, executed with bounded concurrency, a total row budget
    and a total time budget. Input values are the operational job payload;
    per-item *results* never store raw values (only type summaries)."""
    __tablename__ = 'batch_runs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id = db.Column(db.Integer, nullable=False, index=True)
    template_version = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='running', index=True)
    # running | completed | cancelled | interrupted | failed
    stopped_reason = db.Column(db.String(30))   # row_limit | time_limit | cancelled
    idempotency_key = db.Column(db.String(100), unique=True, index=True)
    items_input = db.Column(db.JSON, nullable=False)      # [{values}], job payload
    total_items = db.Column(db.Integer, nullable=False, default=0)
    succeeded_items = db.Column(db.Integer, nullable=False, default=0)
    failed_items = db.Column(db.Integer, nullable=False, default=0)
    cancelled_items = db.Column(db.Integer, nullable=False, default=0)
    skipped_items = db.Column(db.Integer, nullable=False, default=0)
    max_concurrency = db.Column(db.Integer, nullable=False, default=2)
    max_total_rows = db.Column(db.Integer, nullable=False, default=10000)
    max_total_time_ms = db.Column(db.Integer, nullable=False, default=60000)
    item_timeout_ms = db.Column(db.Integer)
    item_delay_ms = db.Column(db.Integer, nullable=False, default=0)
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False)
    total_rows = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'template_id': self.template_id,
            'template_version': self.template_version,
            'status': self.status,
            'stopped_reason': self.stopped_reason,
            'idempotency_key': self.idempotency_key,
            'total_items': self.total_items,
            'succeeded_items': self.succeeded_items,
            'failed_items': self.failed_items,
            'cancelled_items': self.cancelled_items,
            'skipped_items': self.skipped_items,
            'max_concurrency': self.max_concurrency,
            'max_total_rows': self.max_total_rows,
            'max_total_time_ms': self.max_total_time_ms,
            'item_timeout_ms': self.item_timeout_ms,
            'item_delay_ms': self.item_delay_ms,
            'cancel_requested': self.cancel_requested,
            'total_rows': self.total_rows,
            'error': self.error,
            'created_at': self.created_at.isoformat(),
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }

class BatchRunItem(db.Model):
    """One parameter set inside a batch run. Results link the immutable
    template version, a parameter *type* summary and the execution plan —
    never raw parameter values."""
    __tablename__ = 'batch_run_items'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    batch_run_id = db.Column(db.Integer, db.ForeignKey('batch_runs.id'), nullable=False, index=True)
    seq = db.Column(db.Integer, nullable=False)             # stable result order
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    # pending | running | succeeded | failed | cancelled | skipped
    params_summary = db.Column(db.JSON)                     # {name: type_tag}
    ast_hash = db.Column(db.String(32))
    sql = db.Column(db.Text)                                # bound params only, no values
    plan_json = db.Column(db.JSON)
    row_count = db.Column(db.Integer)
    truncated = db.Column(db.Boolean, default=False)
    duration_ms = db.Column(db.Float)
    error = db.Column(db.Text)
    error_code = db.Column(db.String(40))
    started_ts = db.Column(db.Float)                        # epoch seconds (ms precision)
    finished_ts = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('batch_run_id', 'seq', name='uq_batch_item_seq'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'batch_run_id': self.batch_run_id,
            'seq': self.seq,
            'status': self.status,
            'params_summary': self.params_summary or {},
            'ast_hash': self.ast_hash,
            'sql': self.sql,
            'plan_json': self.plan_json,
            'row_count': self.row_count,
            'truncated': self.truncated,
            'duration_ms': self.duration_ms,
            'error': self.error,
            'error_code': self.error_code,
            'started_ts': self.started_ts,
            'finished_ts': self.finished_ts,
        }

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
