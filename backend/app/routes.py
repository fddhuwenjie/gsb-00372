from flask import Blueprint, request, jsonify, make_response
from app.services.metadata_service import MetadataService
from app.services.query_executor import QueryExecutor
from app.services.template_service import (
    TemplateService,
    TemplateValidationError,
    TemplateMigrationError,
    CURRENT_TEMPLATE_VERSION,
)
from app.services.plan_service import diff_plans
from app.services.batch_service import BatchError, BatchRunner
from app.services.utils import generate_token, generate_export_sql
from app.models import SavedQuery, QueryHistory, QueryTemplate, QueryExecution, BatchRun, BatchItem, db
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
                'get': {'summary': 'List query templates'},
                'post': {'summary': 'Create a query template'}
            },
            '/api/templates/{id}': {
                'get': {'summary': 'Get a template'},
                'put': {'summary': 'Update a template'},
                'delete': {'summary': 'Delete a template'}
            },
            '/api/templates/{id}/instantiate': {
                'post': {'summary': 'Instantiate and optionally execute a template'}
            },
            '/api/templates/{id}/share': {
                'post': {'summary': 'Generate a share token for a template'}
            },
            '/api/templates/share/{token}': {
                'get': {'summary': 'Get a shared template by token'}
            }
        }
    }
    return jsonify(spec)


# ======================================================================
# Parameterised query templates
# ======================================================================
@api_bp.route('/templates', methods=['GET'])
def list_templates():
    templates = QueryTemplate.query.order_by(QueryTemplate.updated_at.desc()).all()
    return jsonify([t.to_dict() for t in templates])


@api_bp.route('/templates', methods=['POST'])
def create_template():
    try:
        data = request.get_json() or {}
        definition = data.get('template_definition') or data
        definition = TemplateService.validate_template(definition)
        TemplateService.check_schema(definition)
        template = QueryTemplate(
            name=definition['name'],
            description=definition.get('description', ''),
            template_version=definition.get(
                'template_version', CURRENT_TEMPLATE_VERSION
            ),
            template_definition=definition,
        )
        db.session.add(template)
        db.session.commit()
        return jsonify(template.to_dict()), 201
    except (TemplateValidationError, TemplateMigrationError) as e:
        db.session.rollback()
        return jsonify({'error': str(e), 'errors': getattr(e, 'errors', None)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/<int:template_id>', methods=['GET'])
def get_template(template_id):
    template = QueryTemplate.query.get_or_404(template_id)
    return jsonify(template.to_dict())


@api_bp.route('/templates/<int:template_id>', methods=['PUT'])
def update_template(template_id):
    template = QueryTemplate.query.get_or_404(template_id)
    try:
        data = request.get_json() or {}
        definition = data.get('template_definition') or data
        definition = TemplateService.validate_template(definition)
        TemplateService.check_schema(definition)
        template.name = definition['name']
        template.description = definition.get('description', '')
        template.template_version = definition.get(
            'template_version', CURRENT_TEMPLATE_VERSION
        )
        template.template_definition = definition
        template.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(template.to_dict())
    except (TemplateValidationError, TemplateMigrationError) as e:
        db.session.rollback()
        return jsonify({'error': str(e), 'errors': getattr(e, 'errors', None)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/<int:template_id>', methods=['DELETE'])
def delete_template(template_id):
    template = QueryTemplate.query.get_or_404(template_id)
    db.session.delete(template)
    db.session.commit()
    return '', 204


@api_bp.route('/templates/<int:template_id>/instantiate', methods=['POST'])
def instantiate_template(template_id):
    """
    Instantiate a template: validate and coerce parameters, compile the
    fixed AST to SQL, and optionally execute it.

    Request body:
        {"values": {...}, "execute": true|false}
    """
    template = QueryTemplate.query.get_or_404(template_id)
    data = request.get_json() or {}
    values = data.get('values', {})
    execute = bool(data.get('execute', True))
    try:
        result = TemplateService.instantiate(
            template.template_definition, values
        )
    except (TemplateValidationError, TemplateMigrationError) as e:
        return jsonify({'error': str(e), 'errors': getattr(e, 'errors', None)}), 400

    if not execute:
        return jsonify({
            'sql': result['sql'],
            'params': result['params'],
            'resolvedParameters': result['resolvedParameters'],
            'parameters': TemplateService.describe_parameters(
                template.template_definition
            ),
        })

    try:
        from app.services.query_executor import QueryExecutor
        query_result = QueryExecutor._run(
            result['sql'], result['params'], user_session=get_user_session()
        )
        query_result['resolvedParameters'] = result['resolvedParameters']
        return jsonify(query_result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/templates/validate', methods=['POST'])
def validate_template():
    """Validate a template definition without persisting it."""
    try:
        data = request.get_json() or {}
        definition = TemplateService.validate_template(data)
        TemplateService.check_schema(definition)
        return jsonify({
            'valid': True,
            'template': definition,
            'parameters': TemplateService.describe_parameters(definition),
        })
    except (TemplateValidationError, TemplateMigrationError) as e:
        return jsonify({
            'valid': False,
            'error': str(e),
            'errors': getattr(e, 'errors', None),
        }), 400


@api_bp.route('/templates/<int:template_id>/share', methods=['POST'])
def share_template(template_id):
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
        'url': f'/templates/share/{token}',
        'expires_at': template.share_expires_at.isoformat() if template.share_expires_at else None,
    })


@api_bp.route('/templates/share/<token>', methods=['GET'])
def get_shared_template(token):
    template = QueryTemplate.query.filter_by(share_token=token).first()
    if not template or not template.is_share_valid():
        return jsonify({'error': 'Invalid or expired share token'}), 404
    template.share_access_count = (template.share_access_count or 0) + 1
    db.session.commit()
    return jsonify({
        'template': template.to_dict(),
        'parameters': TemplateService.describe_parameters(
            template.template_definition
        ),
    })


# ======================================================================
# Execution records + plan comparison
# ======================================================================
@api_bp.route('/executions', methods=['GET'])
def list_executions():
    session = get_user_session()
    template_id = request.args.get('template_id', type=int)
    query = QueryExecution.query.filter_by(user_session=session)
    if template_id:
        query = query.filter_by(template_id=template_id)
    records = query.order_by(QueryExecution.created_at.desc()).limit(100).all()
    return jsonify([r.to_dict() for r in records])


@api_bp.route('/executions/<int:execution_id>', methods=['GET'])
def get_execution(execution_id):
    record = QueryExecution.query.get_or_404(execution_id)
    data = record.to_dict()
    data['astStructure'] = record.ast_structure
    return jsonify(data)


@api_bp.route('/plans/diff', methods=['POST'])
def diff_plans_endpoint():
    """
    Compare two recorded executions.

    Body: {"executionIdA": int, "executionIdB": int}
    Returns a change set localised to AST nodes (JOIN, filter, aggregation,
    index access) -- never SQL line numbers.
    """
    data = request.get_json() or {}
    a = QueryExecution.query.get_or_404(data.get('executionIdA'))
    b = QueryExecution.query.get_or_404(data.get('executionIdB'))

    changes = diff_plans(
        a.plan_nodes or [],
        b.plan_nodes or [],
        a.ast_structure or {},
        b.ast_structure or {},
    )

    return jsonify({
        'executionA': a.to_dict(),
        'executionB': b.to_dict(),
        'changes': changes,
        'planFingerprintChanged': a.plan_fingerprint != b.plan_fingerprint,
        'astHashChanged': a.ast_hash != b.ast_hash,
        'rowCountDelta': (b.row_count or 0) - (a.row_count or 0),
        'durationDeltaMs': round(
            (b.duration_ms or 0) - (a.duration_ms or 0), 2
        ),
    })


@api_bp.route('/templates/<int:template_id>/executions', methods=['GET'])
def list_template_executions(template_id):
    """List executions across versions of a template."""
    records = (
        QueryExecution.query
        .filter_by(template_id=template_id)
        .order_by(QueryExecution.created_at.desc())
        .limit(100)
        .all()
    )
    return jsonify([r.to_dict() for r in records])


@api_bp.route('/templates/<int:template_id>/compare-versions', methods=['POST'])
def compare_template_versions(template_id):
    """
    Compare the latest execution of two template versions.

    Body: {"versionA": int, "versionB": int}
    """
    data = request.get_json() or {}
    version_a = data.get('versionA')
    version_b = data.get('versionB')
    if version_a is None or version_b is None:
        return jsonify({'error': 'versionA and versionB are required'}), 400

    a = (
        QueryExecution.query
        .filter_by(template_id=template_id, template_version=version_a)
        .order_by(QueryExecution.created_at.desc())
        .first()
    )
    b = (
        QueryExecution.query
        .filter_by(template_id=template_id, template_version=version_b)
        .order_by(QueryExecution.created_at.desc())
        .first()
    )
    if not a or not b:
        return jsonify({'error': 'No execution found for one of the versions'}), 404

    changes = diff_plans(
        a.plan_nodes or [],
        b.plan_nodes or [],
        a.ast_structure or {},
        b.ast_structure or {},
    )
    return jsonify({
        'versionA': a.to_dict(),
        'versionB': b.to_dict(),
        'changes': changes,
        'planFingerprintChanged': a.plan_fingerprint != b.plan_fingerprint,
    })


# ======================================================================
# Cancellable batch parameter runs
# ======================================================================
@api_bp.route('/batches', methods=['POST'])
def create_batch():
    """
    Submit a batch run of one template version over many parameter sets.

    Body:
        templateId, parameterSets[], concurrency?, maxTotalRows?,
        timeoutSeconds?, idempotencyKey?, labels[]?
    """
    data = request.get_json() or {}
    template_id = data.get('templateId')
    if not template_id:
        return jsonify({'error': 'templateId is required'}), 400
    parameter_sets = data.get('parameterSets')
    if not isinstance(parameter_sets, list):
        return jsonify({'error': 'parameterSets must be a list'}), 400
    try:
        run, created = BatchRunner.create_batch(
            template_id=template_id,
            parameter_sets=parameter_sets,
            idempotency_key=data.get('idempotencyKey'),
            user_session=get_user_session(),
            concurrency=data.get('concurrency'),
            max_total_rows=data.get('maxTotalRows'),
            timeout_seconds=data.get('timeoutSeconds'),
            labels=data.get('labels'),
        )
    except BatchError as exc:
        return jsonify({'error': str(exc)}), 400

    # Execute synchronously (the Flask dev server / test client is
    # single-process; a production deployment would hand this to a
    # worker). Each item still runs in its own thread with bounded
    # concurrency.
    from flask import current_app
    BatchRunner.run_batch(run.id, parameter_sets, app=current_app._get_current_object())
    run = BatchRun.query.get(run.id)
    code = 201 if created else 200
    return jsonify(run.to_dict(include_items=True)), code


@api_bp.route('/batches', methods=['GET'])
def list_batches():
    session = get_user_session()
    runs = (
        BatchRun.query
        .filter_by(user_session=session)
        .order_by(BatchRun.created_at.desc())
        .limit(100)
        .all()
    )
    return jsonify([r.to_dict() for r in runs])


@api_bp.route('/batches/<int:batch_id>', methods=['GET'])
def get_batch(batch_id):
    run = BatchRun.query.get_or_404(batch_id)
    return jsonify(run.to_dict(include_items=True))


@api_bp.route('/batches/<int:batch_id>/cancel', methods=['POST'])
def cancel_batch(batch_id):
    try:
        run = BatchRunner.cancel(batch_id)
    except BatchError as exc:
        return jsonify({'error': str(exc)}), 404
    return jsonify(run.to_dict(include_items=True))


@api_bp.route('/batches/<int:batch_id>/retry', methods=['POST'])
def retry_batch(batch_id):
    data = request.get_json() or {}
    parameter_sets = data.get('parameterSets')
    from flask import current_app
    try:
        run = BatchRunner.retry(
            batch_id, parameter_sets,
            app=current_app._get_current_object(),
        )
    except BatchError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(run.to_dict(include_items=True))


@api_bp.route('/batches/<int:batch_id>/items', methods=['GET'])
def list_batch_items(batch_id):
    BatchRun.query.get_or_404(batch_id)
    items = (
        BatchItem.query
        .filter_by(batch_id=batch_id)
        .order_by(BatchItem.item_index.asc())
        .all()
    )
    return jsonify([i.to_dict() for i in items])
