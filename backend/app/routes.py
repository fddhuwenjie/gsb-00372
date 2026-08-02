from flask import Blueprint, request, jsonify, make_response
from app.services.metadata_service import MetadataService
from app.services.query_executor import QueryExecutor, QueryTimeoutError, QueryCancelledError
from app.services.sql_guard import UnsafeQueryError
from app.services.template_service import (
    TemplateService, TemplateError, SchemaMigrationError,
)
from app.services.plan_analysis_service import PlanAnalysisService
from app.services.batch_run_service import BatchRunService
from app.services.utils import generate_token, generate_export_sql
from app.models import (
    SavedQuery, QueryHistory, QueryTemplate, TemplateVersion,
    ExecutionPlanRecord, BatchRun, BatchRunItem, db,
)
from flask import current_app
from datetime import datetime, timedelta
import uuid
import json

api_bp = Blueprint('api', __name__)

def get_user_session():
    session_id = request.headers.get('X-Session-Id')
    if not session_id:
        session_id = request.cookies.get('session_id', str(uuid.uuid4()))
    return session_id

@api_bp.route('/metadata', methods=['GET'])
def get_metadata():
    """
    Get database metadata (tables, columns, foreign keys)
    ---
    get:
      summary: Get database metadata
      responses:
        200:
          description: Database metadata
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
    """
    try:
        metadata = MetadataService.get_all_metadata()
        return jsonify(metadata)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/generate-sql', methods=['POST'])
def generate_sql():
    """
    Generate SQL from query structure
    ---
    post:
      summary: Generate SQL
      requestBody:
        content:
          application/json:
            schema:
              type: object
      responses:
        200:
          description: Generated SQL with parameters
        400:
          description: Error generating SQL
    """
    try:
        query_structure = request.get_json()
        result = QueryExecutor.generate_sql(query_structure)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/execute-query', methods=['POST'])
def execute_query():
    """
    Execute query and return results
    ---
    post:
      summary: Execute query
      requestBody:
        content:
          application/json:
            schema:
              type: object
      responses:
        200:
          description: Query results
        400:
          description: Error executing query
    """
    try:
        query_structure = request.get_json()
        user_session = get_user_session()
        result = QueryExecutor.execute(query_structure, user_session=user_session)
        return jsonify(result)
    except QueryTimeoutError as e:
        return jsonify({'error': str(e)}), 408
    except QueryCancelledError as e:
        return jsonify({'error': str(e)}), 499
    except UnsafeQueryError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/explain', methods=['POST'])
def explain_query():
    """
    Get execution plan for a query
    ---
    post:
      summary: Explain query plan
      requestBody:
        content:
          application/json:
            schema:
              type: object
      responses:
        200:
          description: Execution plan with nodes and edges
        400:
          description: Error explaining query
    """
    try:
        query_structure = request.get_json()
        result = QueryExecutor.explain(query_structure)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/queries', methods=['GET'])
def list_saved_queries():
    """
    List all saved queries
    ---
    get:
      summary: List saved queries
      responses:
        200:
          description: List of saved queries
    """
    try:
        queries = SavedQuery.query.order_by(SavedQuery.updated_at.desc()).all()
        return jsonify([q.to_dict() for q in queries])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/queries', methods=['POST'])
def create_saved_query():
    """
    Create a new saved query
    ---
    post:
      summary: Create saved query
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                description:
                  type: string
                query_structure:
                  type: object
                chart_config:
                  type: object
      responses:
        201:
          description: Created saved query
        400:
          description: Error creating query
    """
    try:
        data = request.get_json()
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        if not data.get('query_structure'):
            return jsonify({'error': 'Query structure is required'}), 400
        
        query = SavedQuery(
            name=data['name'],
            description=data.get('description', ''),
            query_structure=data['query_structure'],
            chart_config=data.get('chart_config')
        )
        db.session.add(query)
        db.session.commit()
        return jsonify(query.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/queries/<int:query_id>', methods=['GET'])
def get_saved_query(query_id):
    """
    Get a saved query by ID
    ---
    get:
      summary: Get saved query
      parameters:
        - in: path
          name: query_id
          schema:
            type: integer
      responses:
        200:
          description: Saved query
        404:
          description: Query not found
    """
    try:
        query = SavedQuery.query.get_or_404(query_id)
        return jsonify(query.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@api_bp.route('/queries/<int:query_id>', methods=['PUT'])
def update_saved_query(query_id):
    """
    Update a saved query
    ---
    put:
      summary: Update saved query
      parameters:
        - in: path
          name: query_id
          schema:
            type: integer
      requestBody:
        content:
          application/json:
            schema:
              type: object
      responses:
        200:
          description: Updated saved query
        404:
          description: Query not found
    """
    try:
        query = SavedQuery.query.get_or_404(query_id)
        data = request.get_json()
        
        if 'name' in data:
            query.name = data['name']
        if 'description' in data:
            query.description = data['description']
        if 'query_structure' in data:
            query.query_structure = data['query_structure']
        if 'chart_config' in data:
            query.chart_config = data['chart_config']
        
        query.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(query.to_dict())
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/queries/<int:query_id>', methods=['DELETE'])
def delete_saved_query(query_id):
    """
    Delete a saved query
    ---
    delete:
      summary: Delete saved query
      parameters:
        - in: path
          name: query_id
          schema:
            type: integer
      responses:
        204:
          description: Query deleted
        404:
          description: Query not found
    """
    try:
        query = SavedQuery.query.get_or_404(query_id)
        db.session.delete(query)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/queries/<int:query_id>/share', methods=['POST'])
def share_query(query_id):
    """
    Generate a share token for a query
    ---
    post:
      summary: Share query
      parameters:
        - in: path
          name: query_id
          schema:
            type: integer
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                expires_in_hours:
                  type: integer
      responses:
        200:
          description: Share token generated
        404:
          description: Query not found
    """
    try:
        query = SavedQuery.query.get_or_404(query_id)
        data = request.get_json() or {}
        
        token = generate_token(6)
        while SavedQuery.query.filter_by(share_token=token).first():
            token = generate_token(6)
        
        query.share_token = token
        expires_in = data.get('expires_in_hours', 24 * 7)
        if expires_in and expires_in > 0:
            query.share_expires_at = datetime.utcnow() + timedelta(hours=expires_in)
        query.share_access_count = 0
        db.session.commit()
        
        return jsonify({
            'token': token,
            'url': f'/share/{token}',
            'expires_at': query.share_expires_at.isoformat() if query.share_expires_at else None
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/share/<token>', methods=['GET'])
def get_shared_query(token):
    """
    Get a shared query by token (read-only)
    ---
    get:
      summary: Get shared query
      parameters:
        - in: path
          name: token
          schema:
            type: string
      responses:
        200:
          description: Shared query with results
        404:
          description: Token not found or expired
    """
    try:
        query = SavedQuery.query.filter_by(share_token=token).first()
        if not query:
            return jsonify({'error': 'Invalid share token'}), 404
        
        if not query.is_share_valid():
            return jsonify({'error': 'Share link has expired'}), 404
        
        query.share_access_count += 1
        db.session.commit()
        
        result = QueryExecutor.execute(query.query_structure)
        
        return jsonify({
            'query': query.to_dict(),
            'result': result
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/queries/<int:query_id>/export', methods=['GET'])
def export_query(query_id):
    """
    Export a query as SQL file
    ---
    get:
      summary: Export query as SQL
      parameters:
        - in: path
          name: query_id
          schema:
            type: integer
      responses:
        200:
          description: SQL file download
        404:
          description: Query not found
    """
    try:
        query = SavedQuery.query.get_or_404(query_id)
        
        sql_result = QueryExecutor.generate_sql(query.query_structure)
        export_content = generate_export_sql(
            query_name=query.name,
            created_at=query.created_at.isoformat(),
            query_structure=query.query_structure,
            sql=sql_result['sql'],
            params=sql_result['params']
        )
        
        filename = f"{query.name.replace(' ', '_')}.sql"
        response = make_response(export_content)
        response.headers['Content-Type'] = 'application/sql'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/history', methods=['GET'])
def get_query_history():
    """
    Get query history for current user session
    ---
    get:
      summary: Get query history
      responses:
        200:
          description: List of recent queries
    """
    try:
        user_session = get_user_session()
        records = QueryHistory.query.filter_by(
            user_session=user_session
        ).order_by(QueryHistory.created_at.desc()).limit(50).all()
        return jsonify([r.to_dict() for r in records])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =====================================================================
# Query Templates (reusable, parameterized queries)
# =====================================================================

def _template_error_status(e):
    if isinstance(e, SchemaMigrationError):
        return 409
    if isinstance(e, TemplateError):
        return 400
    return 400


@api_bp.route('/templates', methods=['GET'])
def list_templates():
    try:
        templates = QueryTemplate.query.order_by(QueryTemplate.updated_at.desc()).all()
        return jsonify([t.to_dict() for t in templates])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/templates', methods=['POST'])
def create_template():
    try:
        data = request.get_json() or {}
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400

        template_def = {
            'queryStructure': data.get('query_structure'),
            'parameters': data.get('parameters') or [],
        }
        # Validate declarations + value-only placeholders before persisting.
        TemplateService.validate_template(template_def)

        template = QueryTemplate(
            name=data['name'],
            description=data.get('description', ''),
            query_structure=template_def['queryStructure'],
            parameters=template_def['parameters'],
            current_version=1,
        )
        db.session.add(template)
        db.session.flush()
        db.session.add(TemplateVersion(
            template_id=template.id, version=1,
            query_structure=template.query_structure,
            parameters=template.parameters,
        ))
        db.session.commit()
        return jsonify(template.to_dict(include_versions=True)), 201
    except TemplateError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), _template_error_status(e)
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/parameterize', methods=['POST'])
def parameterize_query():
    """Derive a template (queryStructure + parameters) from a concrete query
    AST plus a list of parameterization specs. Values only, no structure."""
    try:
        data = request.get_json() or {}
        template_def = TemplateService.parameterize(
            data.get('query_structure'), data.get('specs') or []
        )
        return jsonify(template_def)
    except TemplateError as e:
        return jsonify({'error': str(e)}), _template_error_status(e)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/<int:template_id>', methods=['GET'])
def get_template(template_id):
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        return jsonify(template.to_dict(include_versions=True))
    except Exception as e:
        return jsonify({'error': str(e)}), 404


@api_bp.route('/templates/<int:template_id>', methods=['PUT'])
def update_template(template_id):
    """Update a template. Any change to the definition bumps the version and
    snapshots the new definition so prior versions remain instantiable."""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}

        if 'name' in data:
            template.name = data['name']
        if 'description' in data:
            template.description = data['description']

        definition_changed = False
        new_qs = data.get('query_structure', template.query_structure)
        new_params = data.get('parameters', template.parameters)
        if 'query_structure' in data or 'parameters' in data:
            TemplateService.validate_template({
                'queryStructure': new_qs, 'parameters': new_params,
            })
            if new_qs != template.query_structure or new_params != template.parameters:
                definition_changed = True

        if definition_changed:
            template.query_structure = new_qs
            template.parameters = new_params
            template.current_version += 1
            db.session.add(TemplateVersion(
                template_id=template.id, version=template.current_version,
                query_structure=new_qs, parameters=new_params,
            ))

        template.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(template.to_dict(include_versions=True))
    except TemplateError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), _template_error_status(e)
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/<int:template_id>', methods=['DELETE'])
def delete_template(template_id):
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        db.session.delete(template)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


def _load_template_definition(template, version):
    """Return (query_structure, parameters) for the requested version, or the
    current definition when version is None."""
    if version is None or version == template.current_version:
        return template.query_structure, template.parameters
    snapshot = TemplateVersion.query.filter_by(
        template_id=template.id, version=version
    ).first()
    if not snapshot:
        raise TemplateError(f'Template version {version} not found')
    return snapshot.query_structure, snapshot.parameters


def _instantiate_and_run(query_structure, parameters, values, mode, user_session=None):
    template_def = {'queryStructure': query_structure, 'parameters': parameters}
    metadata = MetadataService.get_all_metadata()
    concrete = TemplateService.instantiate(template_def, values, metadata=metadata)
    if mode == 'sql':
        return QueryExecutor.generate_sql(concrete)
    if mode == 'explain':
        return QueryExecutor.explain(concrete)
    return QueryExecutor.execute(concrete, user_session=user_session)


@api_bp.route('/templates/<int:template_id>/instantiate', methods=['POST'])
def instantiate_template(template_id):
    """Bind values into a template version and run it. ``mode`` selects
    execute (default), sql or explain -- all go through the one SQL source and
    the read-only executor."""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}
        version = data.get('version')
        values = data.get('values') or {}
        mode = data.get('mode', 'execute')

        query_structure, parameters = _load_template_definition(template, version)
        result = _instantiate_and_run(
            query_structure, parameters, values, mode,
            user_session=get_user_session(),
        )
        return jsonify(result)
    except SchemaMigrationError as e:
        return jsonify({'error': str(e), 'migration': e.references}), 409
    except TemplateError as e:
        return jsonify({'error': str(e)}), _template_error_status(e)
    except QueryTimeoutError as e:
        return jsonify({'error': str(e)}), 408
    except QueryCancelledError as e:
        return jsonify({'error': str(e)}), 499
    except UnsafeQueryError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/<int:template_id>/check-schema', methods=['GET'])
def check_template_schema(template_id):
    """Report whether a template still matches the live schema (locatable)."""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        metadata = MetadataService.get_all_metadata()
        TemplateService.check_schema(
            template.query_structure, metadata, template.parameters or []
        )
        return jsonify({'ok': True, 'migration': []})
    except SchemaMigrationError as e:
        return jsonify({'ok': False, 'error': str(e), 'migration': e.references}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/<int:template_id>/share', methods=['POST'])
def share_template(template_id):
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}
        token = generate_token(6)
        while QueryTemplate.query.filter_by(share_token=token).first():
            token = generate_token(6)
        template.share_token = token
        expires_in = data.get('expires_in_hours', 24 * 7)
        if expires_in and expires_in > 0:
            template.share_expires_at = datetime.utcnow() + timedelta(hours=expires_in)
        template.share_access_count = 0
        db.session.commit()
        return jsonify({
            'token': token,
            'url': f'/template-share/{token}',
            'expires_at': template.share_expires_at.isoformat() if template.share_expires_at else None,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/template-share/<token>', methods=['GET'])
def get_shared_template(token):
    try:
        template = QueryTemplate.query.filter_by(share_token=token).first()
        if not template or not template.is_share_valid():
            return jsonify({'error': 'Invalid or expired share token'}), 404
        template.share_access_count += 1
        db.session.commit()
        # Share exposes the definition (with parameters) so the recipient can
        # instantiate with their own values; references stay intact via ids.
        return jsonify({'template': template.to_dict(include_versions=True)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# =====================================================================
# Execution plan capture & version comparison
# =====================================================================

@api_bp.route('/templates/<int:template_id>/plan-record', methods=['POST'])
def record_template_plan(template_id):
    """Instantiate a template version and capture its execution plan record
    (AST hash, param type summary, normalized plan, duration, rows). Values are
    used only to run the query; only their *types* are persisted."""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}
        version = data.get('version', template.current_version)
        values = data.get('values') or {}

        query_structure, parameters = _load_template_definition(template, version)
        template_def = {'queryStructure': query_structure, 'parameters': parameters}
        metadata = MetadataService.get_all_metadata()
        concrete = TemplateService.instantiate(template_def, values, metadata=metadata)

        record = QueryExecutor.capture_plan_record(
            concrete, template_id=template.id, template_version=version,
        )
        return jsonify(record), 201
    except SchemaMigrationError as e:
        return jsonify({'error': str(e), 'migration': e.references}), 409
    except TemplateError as e:
        return jsonify({'error': str(e)}), 400
    except QueryTimeoutError as e:
        return jsonify({'error': str(e)}), 408
    except QueryCancelledError as e:
        return jsonify({'error': str(e)}), 499
    except UnsafeQueryError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/<int:template_id>/plan-records', methods=['GET'])
def list_template_plan_records(template_id):
    try:
        QueryTemplate.query.get_or_404(template_id)
        version = request.args.get('version', type=int)
        q = ExecutionPlanRecord.query.filter_by(template_id=template_id)
        if version is not None:
            q = q.filter_by(template_version=version)
        records = q.order_by(ExecutionPlanRecord.created_at.desc()).all()
        return jsonify([r.to_dict() for r in records])
    except Exception as e:
        return jsonify({'error': str(e)}), 400


def _latest_record_for_version(template_id, version):
    return (ExecutionPlanRecord.query
            .filter_by(template_id=template_id, template_version=version)
            .order_by(ExecutionPlanRecord.created_at.desc())
            .first())


@api_bp.route('/templates/<int:template_id>/compare-plans', methods=['POST'])
def compare_template_plans(template_id):
    """Compare the execution plans and results of two template versions.

    Body: {versionA, versionB, values?} -- if a version has no captured record
    yet, one is captured on the fly using the supplied (type-only-persisted)
    values. Returns an AST-located change set plus cost deltas.
    """
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}
        version_a = data.get('versionA')
        version_b = data.get('versionB')
        if version_a is None or version_b is None:
            return jsonify({'error': 'versionA and versionB are required'}), 400
        values = data.get('values') or {}
        metadata = MetadataService.get_all_metadata()

        def record_for(version):
            existing = None if data.get('fresh') else _latest_record_for_version(template.id, version)
            if existing:
                return existing.to_dict()
            qs, params = _load_template_definition(template, version)
            concrete = TemplateService.instantiate(
                {'queryStructure': qs, 'parameters': params}, values, metadata=metadata
            )
            return QueryExecutor.capture_plan_record(
                concrete, template_id=template.id, template_version=version,
            )

        rec_a = record_for(version_a)
        rec_b = record_for(version_b)
        comparison = PlanAnalysisService.compare_records(rec_a, rec_b)
        comparison['versionA'] = version_a
        comparison['versionB'] = version_b
        return jsonify(comparison)
    except SchemaMigrationError as e:
        return jsonify({'error': str(e), 'migration': e.references}), 409
    except TemplateError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# =====================================================================
# Batch parameter runs (cancellable, concurrency + budget limited)
# =====================================================================

@api_bp.route('/templates/<int:template_id>/batch-runs', methods=['POST'])
def submit_batch_run(template_id):
    """Submit a batch run of one immutable template version against many
    parameter sets. Idempotent on ``idempotency_key``: a repeated submit with
    the same key returns the existing batch instead of creating a new one."""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}
        version = data.get('version', template.current_version)
        value_sets = data.get('value_sets')
        idempotency_key = data.get('idempotency_key')

        if idempotency_key:
            existing = BatchRun.query.filter_by(idempotency_key=idempotency_key).first()
            if existing:
                # Duplicate submit: return the already-created batch untouched.
                return jsonify(existing.to_dict()), 200

        query_structure, parameters = _load_template_definition(template, version)

        batch_id = BatchRunService.create_batch(
            template, version, query_structure, parameters, value_sets,
            max_concurrency=data.get('max_concurrency', 4),
            max_total_rows=data.get('max_total_rows'),
            max_total_ms=data.get('max_total_ms'),
            per_item_timeout_ms=data.get('per_item_timeout_ms', 5000),
            per_item_max_rows=data.get('per_item_max_rows', 1000),
            idempotency_key=idempotency_key,
        )

        BatchRunService.start_batch(
            current_app._get_current_object(), batch_id,
            query_structure, parameters, value_sets,
        )

        batch = db.session.get(BatchRun, batch_id)
        return jsonify(batch.to_dict()), 201
    except TemplateError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/<int:template_id>/batch-runs', methods=['GET'])
def list_batch_runs(template_id):
    try:
        QueryTemplate.query.get_or_404(template_id)
        runs = (BatchRun.query.filter_by(template_id=template_id)
                .order_by(BatchRun.created_at.desc()).all())
        return jsonify([r.to_dict(include_items=False) for r in runs])
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/batch-runs/<int:batch_id>', methods=['GET'])
def get_batch_run(batch_id):
    """Full, recoverable status: batch + every item's durable state."""
    try:
        # Item states are written by worker threads in separate sessions; drop
        # this session's cache so polling always reflects the durable truth.
        db.session.expire_all()
        batch = db.session.get(BatchRun, batch_id)
        if batch is None:
            return jsonify({'error': 'Batch run not found'}), 404
        return jsonify(batch.to_dict(include_items=True))
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/batch-runs/<int:batch_id>/cancel', methods=['POST'])
def cancel_batch_run(batch_id):
    """Request cancellation. Sets a durable flag and signals live workers; no
    further item results will be written after this."""
    try:
        batch = db.session.get(BatchRun, batch_id)
        if batch is None:
            return jsonify({'error': 'Batch run not found'}), 404
        batch.cancel_requested = True
        db.session.commit()
        BatchRunService.request_cancel(batch_id)
        return jsonify(batch.to_dict(include_items=False))
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/batch-runs/<int:batch_id>/retry', methods=['POST'])
def retry_batch_run(batch_id):
    """Re-run only the items that did not succeed. Succeeded items keep their
    results; the batch is reset to running for the remaining items."""
    try:
        batch = db.session.get(BatchRun, batch_id)
        if batch is None:
            return jsonify({'error': 'Batch run not found'}), 404
        data = request.get_json() or {}
        value_sets = data.get('value_sets')
        if not value_sets:
            return jsonify({'error': 'value_sets required to retry (values are not stored)'}), 400

        # Clear the durable cancel flag so a retry can proceed. Flip to running
        # synchronously so a status poll can never observe the stale terminal
        # state from the previous run before the worker thread starts.
        batch.cancel_requested = False
        batch.finished_at = None
        batch.status = 'running'
        db.session.commit()

        template = db.session.get(QueryTemplate, batch.template_id)
        query_structure, parameters = _load_template_definition(template, batch.template_version)

        BatchRunService.start_batch(
            current_app._get_current_object(), batch_id,
            query_structure, parameters, value_sets, retry=True,
        )
        return jsonify(db.session.get(BatchRun, batch_id).to_dict())
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/openapi.json', methods=['GET'])
def get_openapi_spec():
    spec = {
        'openapi': '3.0.0',
        'info': {
            'title': 'Visual Query Builder API',
            'version': '1.0.0',
            'description': 'API for the visual SQL query builder application'
        },
        'paths': {
            '/api/metadata': {
                'get': {'summary': 'Get database metadata'}
            },
            '/api/generate-sql': {
                'post': {'summary': 'Generate SQL from query structure'}
            },
            '/api/execute-query': {
                'post': {'summary': 'Execute query and return results'}
            },
            '/api/explain': {
                'post': {'summary': 'Get execution plan for a query'}
            },
            '/api/queries': {
                'get': {'summary': 'List all saved queries'},
                'post': {'summary': 'Create a new saved query'}
            },
            '/api/queries/{query_id}': {
                'get': {'summary': 'Get a saved query by ID'},
                'put': {'summary': 'Update a saved query'},
                'delete': {'summary': 'Delete a saved query'}
            },
            '/api/queries/{query_id}/share': {
                'post': {'summary': 'Generate a share token for a query'}
            },
            '/api/share/{token}': {
                'get': {'summary': 'Get a shared query by token'}
            },
            '/api/queries/{query_id}/export': {
                'get': {'summary': 'Export a query as SQL file'}
            },
            '/api/history': {
                'get': {'summary': 'Get query history for current user session'}
            }
        }
    }
    return jsonify(spec)
