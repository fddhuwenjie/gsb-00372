from flask import Blueprint, request, jsonify, make_response
from sqlalchemy import text
from collections import Counter
from app.services.metadata_service import MetadataService
from app.services.query_executor import QueryExecutor, QueryCancelled, QueryTimeout
from app.services.template_service import TemplateService, TemplateError
from app.services.sql_generator import SQLGenerator
from app.services.plan_service import (
    ast_hash, normalize_explain_plan, diff_query_structures, diff_plans,
)
from app.services.batch_service import BatchService
from app.services.utils import generate_token, generate_export_sql
from app.models import (
    SavedQuery, QueryHistory, QueryTemplate, TemplateVersion, ExecutionSnapshot,
    BatchRun, BatchRunItem, db,
)
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
    except QueryCancelled as e:
        return jsonify({'error': str(e), 'cancelled': True}), 499
    except QueryTimeout as e:
        return jsonify({'error': str(e), 'timeout': True}), 408
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/cancel-query', methods=['POST'])
def cancel_query():
    """
    Cancel the query currently running for the caller's session
    ---
    post:
      summary: Cancel running query
      responses:
        200:
          description: Cancellation requested
    """
    user_session = get_user_session()
    QueryExecutor.request_cancel(user_session)
    return jsonify({'cancelled': True})

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

# ---------------------------------------------------------------------------
# Parameterized query templates
# ---------------------------------------------------------------------------

def _template_error_response(e):
    body = {'error': str(e)}
    if e.issues:
        body['issues'] = e.issues
    return jsonify(body), e.status

def _sample_value(param):
    """Type-appropriate sample used to smoke-generate a template at
    authoring time (required parameters have no default to fall back to)."""
    ptype = param.get('type', 'string')
    if ptype.endswith('[]'):
        return []
    return {
        'string': '',
        'integer': 0,
        'number': 0,
        'boolean': True,
        'date': '1970-01-01',
        'datetime': '1970-01-01T00:00:00',
    }.get(ptype, '')

def _archive_template_version(template):
    """Snapshot the current template (parameters + AST) as an immutable
    version row so any two versions can be compared later."""
    row = TemplateVersion(
        template_id=template.id,
        version=template.version,
        parameters=template.parameters or [],
        query_structure=template.query_structure,
    )
    db.session.add(row)
    db.session.commit()

def _validate_template_payload(parameters, query_structure):
    """Authoring-time validation: definition rules + current schema + the
    template must generate SQL once instantiated with defaults."""
    TemplateService.validate_definition(parameters, query_structure)
    metadata = MetadataService.get_all_metadata()
    issues = TemplateService.validate_against_schema(parameters, query_structure, metadata)
    if issues:
        raise TemplateError('Template does not match the current schema',
                            issues=issues, status=400)
    # smoke-generate with defaults (samples for required params) to prove
    # the template is executable
    defaults = {
        p['name']: p.get('default', _sample_value(p)) for p in (parameters or [])
    }
    ast = TemplateService.instantiate(parameters, query_structure, defaults)
    generator = SQLGenerator(ast)
    generator.generate()

@api_bp.route('/templates', methods=['GET'])
def list_templates():
    """List all parameterized query templates"""
    try:
        templates = QueryTemplate.query.order_by(QueryTemplate.updated_at.desc()).all()
        return jsonify([t.to_dict() for t in templates])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/templates', methods=['POST'])
def create_template():
    """Create a parameterized query template (version starts at 1)"""
    try:
        data = request.get_json()
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        if not data.get('query_structure'):
            return jsonify({'error': 'Query structure is required'}), 400

        parameters = data.get('parameters') or []
        _validate_template_payload(parameters, data['query_structure'])

        template = QueryTemplate(
            name=data['name'],
            description=data.get('description', ''),
            version=1,
            parameters=parameters,
            query_structure=data['query_structure'],
        )
        db.session.add(template)
        db.session.commit()
        _archive_template_version(template)
        return jsonify(template.to_dict()), 201
    except TemplateError as e:
        db.session.rollback()
        return _template_error_response(e)
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>', methods=['GET'])
def get_template(template_id):
    """Get a template by ID"""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        return jsonify(template.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@api_bp.route('/templates/<int:template_id>', methods=['PUT'])
def update_template(template_id):
    """Update a template; changing parameters or query structure bumps the version"""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json()

        new_parameters = data.get('parameters', template.parameters or [])
        new_structure = data.get('query_structure', template.query_structure)

        structure_changed = (
            'parameters' in data and data['parameters'] != (template.parameters or [])
        ) or (
            'query_structure' in data and data['query_structure'] != template.query_structure
        )

        if 'parameters' in data or 'query_structure' in data:
            _validate_template_payload(new_parameters, new_structure)

        if 'name' in data:
            template.name = data['name']
        if 'description' in data:
            template.description = data['description']
        if structure_changed:
            template.parameters = new_parameters
            template.query_structure = new_structure
            template.version = (template.version or 1) + 1

        template.updated_at = datetime.utcnow()
        db.session.commit()
        if structure_changed:
            _archive_template_version(template)
        return jsonify(template.to_dict())
    except TemplateError as e:
        db.session.rollback()
        return _template_error_response(e)
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>', methods=['DELETE'])
def delete_template(template_id):
    """Delete a template"""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        db.session.delete(template)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>/instantiate', methods=['POST'])
def instantiate_template(template_id):
    """Instantiate a template with parameter values.

    Only values are substituted; the SQL structure always comes from the
    stored template AST. Schema drift yields a locatable migration error.
    """
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}
        values = data.get('values') or {}

        metadata = MetadataService.get_all_metadata()
        issues = TemplateService.validate_against_schema(
            template.parameters or [], template.query_structure, metadata)
        if issues:
            return jsonify({
                'error': 'Template requires migration: schema references changed',
                'issues': issues,
            }), 409

        ast = TemplateService.instantiate(template.parameters or [],
                                          template.query_structure, values)
        response = {
            'query_structure': ast,
            'template_id': template.id,
            'version': template.version,
        }
        result = QueryExecutor.generate_sql(ast)
        response['sql'] = result['sql']
        response['params'] = result['params']

        if data.get('execute'):
            user_session = get_user_session()
            response['result'] = QueryExecutor.execute(
                ast, user_session=user_session,
                template_id=template.id, template_version=template.version)

        return jsonify(response)
    except QueryCancelled as e:
        return jsonify({'error': str(e), 'cancelled': True}), 499
    except QueryTimeout as e:
        return jsonify({'error': str(e), 'timeout': True}), 408
    except TemplateError as e:
        return _template_error_response(e)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>/validate', methods=['GET'])
def validate_template(template_id):
    """Validate a template against the current schema (migration check)"""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        metadata = MetadataService.get_all_metadata()
        issues = TemplateService.validate_against_schema(
            template.parameters or [], template.query_structure, metadata)
        return jsonify({'valid': not issues, 'issues': issues,
                        'version': template.version})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>/versions', methods=['GET'])
def list_template_versions(template_id):
    """List archived versions of a template"""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        rows = TemplateVersion.query.filter_by(template_id=template_id) \
            .order_by(TemplateVersion.version.asc()).all()
        versions = [{'version': r.version, 'created_at': r.created_at.isoformat()}
                    for r in rows]
        if not any(v['version'] == template.version for v in versions):
            versions.append({'version': template.version,
                             'created_at': template.updated_at.isoformat()})
            versions.sort(key=lambda v: v['version'])
        return jsonify(versions)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>/compare', methods=['POST'])
def compare_template_versions(template_id):
    """Compare two versions of one template: AST change set, normalized
    plan change set and (optionally) live result differences. All changes
    are localized to AST nodes, never to SQL string positions."""
    try:
        template = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}
        from_version = data.get('from_version')
        to_version = data.get('to_version', template.version)
        values = data.get('values') or {}
        include_results = bool(data.get('include_results', True))

        if not from_version:
            return jsonify({'error': 'from_version is required'}), 400

        def load_version(v):
            if v == template.version:
                return template.parameters or [], template.query_structure
            row = TemplateVersion.query.filter_by(template_id=template_id, version=v).first()
            if not row:
                raise TemplateError(f'Version {v} not found for template {template_id}',
                                    status=404)
            return row.parameters or [], row.query_structure

        def build_side(v):
            parameters, structure = load_version(v)
            declared = {p.get('name') for p in parameters}
            side_values = {k: val for k, val in values.items() if k in declared}
            ast = TemplateService.instantiate(parameters, structure, side_values)
            gen = SQLGenerator(ast)
            return {
                'version': v, 'ast': ast,
                'sql': gen.generate(), 'params': gen.get_params(),
            }

        side_a = build_side(from_version)
        side_b = build_side(to_version)

        with db.engine.connect() as connection:
            for side in (side_a, side_b):
                rows = connection.execute(
                    text(f'EXPLAIN QUERY PLAN {side["sql"]}'), side['params']).fetchall()
                side['plan'] = normalize_explain_plan(
                    [tuple(r) for r in rows], QueryExecutor._alias_map(side['ast']))

        result_diff = None
        if include_results:
            res_a = QueryExecutor.execute(side_a['ast'], record_snapshot=False)
            res_b = QueryExecutor.execute(side_b['ast'], record_snapshot=False)
            cols_a = [c['name'] for c in res_a['columns']]
            cols_b = [c['name'] for c in res_b['columns']]
            rows_a = Counter(tuple(r) for r in res_a['rows'])
            rows_b = Counter(tuple(r) for r in res_b['rows'])
            result_diff = {
                'columns_added': [c for c in cols_b if c not in cols_a],
                'columns_removed': [c for c in cols_a if c not in cols_b],
                'rows_from': res_a['rowCount'],
                'rows_to': res_b['rowCount'],
                'rows_only_in_from': sum((rows_a - rows_b).values()),
                'rows_only_in_to': sum((rows_b - rows_a).values()),
                'duration_from_ms': res_a['executionTime'],
                'duration_to_ms': res_b['executionTime'],
            }

        return jsonify({
            'from_version': from_version,
            'to_version': to_version,
            'ast_hash_from': ast_hash(side_a['ast']),
            'ast_hash_to': ast_hash(side_b['ast']),
            'ast_changes': diff_query_structures(side_a['ast'], side_b['ast']),
            'plan_changes': diff_plans(side_a['plan'], side_b['plan']),
            'plan_from': side_a['plan'],
            'plan_to': side_b['plan'],
            'result_diff': result_diff,
        })
    except TemplateError as e:
        return _template_error_response(e)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/executions', methods=['GET'])
def list_executions():
    """List execution snapshots (AST hash, parameter type summary,
    normalized plan, duration, row count — never raw parameter values)."""
    try:
        template_id = request.args.get('template_id', type=int)
        limit = min(request.args.get('limit', 50, type=int) or 50, 200)
        query = ExecutionSnapshot.query
        if template_id:
            query = query.filter_by(template_id=template_id)
        records = query.order_by(ExecutionSnapshot.created_at.desc()).limit(limit).all()
        return jsonify([r.to_dict() for r in records])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/templates/<int:template_id>/share', methods=['POST'])
def share_template(template_id):
    """Generate a share token for a template"""
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
            'url': f'/share/template/{token}',
            'expires_at': template.share_expires_at.isoformat() if template.share_expires_at else None
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/share/template/<token>', methods=['GET'])
def get_shared_template(token):
    """Get a shared template by token (read-only, references preserved)"""
    try:
        template = QueryTemplate.query.filter_by(share_token=token).first()
        if not template:
            return jsonify({'error': 'Invalid share token'}), 404
        if not template.is_share_valid():
            return jsonify({'error': 'Share link has expired'}), 404

        template.share_access_count += 1
        db.session.commit()
        return jsonify({'template': template.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ---------------------------------------------------------------------------
# Batch parameter runs
# ---------------------------------------------------------------------------

@api_bp.route('/batch-runs', methods=['POST'])
def create_batch_run():
    """Create a batch parameter run for one immutable template version.
    Idempotent when an idempotency_key is supplied."""
    try:
        data = request.get_json() or {}
        template_id = data.get('template_id')
        if not template_id:
            return jsonify({'error': 'template_id is required'}), 400
        template = QueryTemplate.query.get(template_id)
        if not template:
            return jsonify({'error': f'Template {template_id} not found'}), 404

        version = data.get('version', template.version)
        items = data.get('items') or []
        limits = {
            'max_concurrency': data.get('max_concurrency', 2),
            'max_total_rows': data.get('max_total_rows', 10000),
            'max_total_time_ms': data.get('max_total_time_ms', 60000),
            'item_timeout_ms': data.get('item_timeout_ms'),
            'item_delay_ms': data.get('item_delay_ms', 0),
        }
        batch, created = BatchService.create_batch(
            template, version, items, limits,
            idempotency_key=data.get('idempotency_key'),
        )
        return jsonify(batch.to_dict()), 201 if created else 200
    except TemplateError as e:
        db.session.rollback()
        return _template_error_response(e)
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/batch-runs', methods=['GET'])
def list_batch_runs():
    """List batch runs, optionally filtered by template"""
    try:
        template_id = request.args.get('template_id', type=int)
        query = BatchRun.query
        if template_id:
            query = query.filter_by(template_id=template_id)
        records = query.order_by(BatchRun.created_at.desc()).limit(100).all()
        return jsonify([r.to_dict() for r in records])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/batch-runs/<int:batch_id>', methods=['GET'])
def get_batch_run(batch_id):
    """Get batch run status and counters"""
    try:
        batch = db.session.get(BatchRun, batch_id)
        if not batch:
            return jsonify({'error': 'Batch run not found'}), 404
        return jsonify(batch.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/batch-runs/<int:batch_id>/items', methods=['GET'])
def get_batch_run_items(batch_id):
    """Get per-item results in stable seq order (no raw parameter values)"""
    try:
        items = BatchRunItem.query.filter_by(batch_run_id=batch_id) \
            .order_by(BatchRunItem.seq.asc()).all()
        return jsonify([i.to_dict() for i in items])
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/batch-runs/<int:batch_id>/cancel', methods=['POST'])
def cancel_batch_run(batch_id):
    """Request cancellation: in-flight items abort, no further results written"""
    try:
        batch = BatchService.cancel(batch_id)
        return jsonify(batch.to_dict())
    except TemplateError as e:
        return _template_error_response(e)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/batch-runs/<int:batch_id>/retry', methods=['POST'])
def retry_batch_run(batch_id):
    """Re-run only items that did not succeed (failed/cancelled/skipped)"""
    try:
        batch = BatchService.retry(batch_id)
        return jsonify(batch.to_dict())
    except TemplateError as e:
        return _template_error_response(e)
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

@api_bp.route('/openapi.json', methods=['GET'])
def get_openapi_spec():
    """
    Get OpenAPI specification
    """
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
            },
            '/api/templates': {
                'get': {'summary': 'List parameterized query templates'},
                'post': {'summary': 'Create a parameterized query template'}
            },
            '/api/templates/{template_id}': {
                'get': {'summary': 'Get a template by ID'},
                'put': {'summary': 'Update a template (bumps version on structure change)'},
                'delete': {'summary': 'Delete a template'}
            },
            '/api/templates/{template_id}/instantiate': {
                'post': {'summary': 'Instantiate a template with parameter values (values only, never structure)'}
            },
            '/api/templates/{template_id}/validate': {
                'get': {'summary': 'Validate a template against the current schema'}
            },
            '/api/templates/{template_id}/share': {
                'post': {'summary': 'Generate a share token for a template'}
            },
            '/api/share/template/{token}': {
                'get': {'summary': 'Get a shared template by token'}
            }
        }
    }
    return jsonify(spec)
