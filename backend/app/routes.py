from flask import Blueprint, request, jsonify, make_response, current_app
from app.services.metadata_service import MetadataService
from app.services.query_executor import QueryExecutor
from app.services.template_service import TemplateService, TemplateValidationError
from app.services.plan_service import (
    compute_ast_hash, compute_param_type_summary, normalize_explain_plan,
    diff_plans, create_snapshot,
)
from app.services.batch_service import BatchService
from app.services.utils import generate_token, generate_export_sql
from app.models import (
    SavedQuery, QueryHistory, QueryTemplate, PlanSnapshot,
    BatchRun, BatchItem, db,
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

# --- Query Template routes ---

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
        data = request.get_json()
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        if not data.get('query_structure'):
            return jsonify({'error': 'Query structure is required'}), 400

        parameters = data.get('parameters', [])
        built = TemplateService.build_template(
            name=data['name'],
            query_structure=data['query_structure'],
            parameters=parameters,
            description=data.get('description', ''),
            version=1,
        )

        tpl = QueryTemplate(
            name=built['name'],
            description=built['description'],
            version=built['version'],
            query_structure=built['query_structure'],
            parameters=built['parameters'],
            schema_refs=built['schema_refs'],
        )
        db.session.add(tpl)
        db.session.commit()
        return jsonify(tpl.to_dict()), 201
    except TemplateValidationError as e:
        return jsonify({'error': str(e), 'errors': e.errors}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>', methods=['GET'])
def get_template(template_id):
    try:
        tpl = QueryTemplate.query.get_or_404(template_id)
        return jsonify(tpl.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@api_bp.route('/templates/<int:template_id>', methods=['PUT'])
def update_template(template_id):
    try:
        tpl = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json()

        if 'name' in data:
            tpl.name = data['name']
        if 'description' in data:
            tpl.description = data['description']

        if 'query_structure' in data or 'parameters' in data:
            new_qs = data.get('query_structure', tpl.query_structure)
            new_params = data.get('parameters', tpl.parameters)
            built = TemplateService.build_template(
                name=tpl.name,
                query_structure=new_qs,
                parameters=new_params,
                description=tpl.description or '',
                version=tpl.version + 1,
            )
            tpl.query_structure = built['query_structure']
            tpl.parameters = built['parameters']
            tpl.schema_refs = built['schema_refs']
            tpl.version = built['version']

        tpl.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(tpl.to_dict())
    except TemplateValidationError as e:
        db.session.rollback()
        return jsonify({'error': str(e), 'errors': e.errors}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>', methods=['DELETE'])
def delete_template(template_id):
    try:
        tpl = QueryTemplate.query.get_or_404(template_id)
        db.session.delete(tpl)
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>/instantiate', methods=['POST'])
def instantiate_template(template_id):
    try:
        tpl = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}
        param_values = data.get('parameters', {})

        template_dict = tpl.to_dict()
        concrete = TemplateService.instantiate(template_dict, param_values)
        result = QueryExecutor.generate_sql(concrete)

        return jsonify({
            'queryStructure': concrete,
            'sql': result['sql'],
            'params': result['params'],
            'templateVersion': tpl.version,
        })
    except TemplateValidationError as e:
        return jsonify({'error': str(e), 'errors': e.errors}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>/execute', methods=['POST'])
def execute_template(template_id):
    try:
        tpl = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}
        param_values = data.get('parameters', {})
        user_session = get_user_session()
        capture = data.get('captureSnapshot', False)
        label = data.get('label')

        template_dict = tpl.to_dict()
        concrete = TemplateService.instantiate(template_dict, param_values)
        result = QueryExecutor.execute(
            concrete,
            user_session=user_session,
            capture_snapshot=capture,
            template_id=tpl.id,
            template_version=tpl.version,
            parameters=tpl.parameters,
            label=label,
        )
        result['templateVersion'] = tpl.version
        return jsonify(result)
    except TemplateValidationError as e:
        return jsonify({'error': str(e), 'errors': e.errors}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>/validate', methods=['POST'])
def validate_template(template_id):
    try:
        tpl = QueryTemplate.query.get_or_404(template_id)
        schema_errors = TemplateService.validate_against_schema(tpl.to_dict())
        return jsonify({
            'valid': len(schema_errors) == 0,
            'errors': schema_errors,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/templates/<int:template_id>/share', methods=['POST'])
def share_template(template_id):
    try:
        tpl = QueryTemplate.query.get_or_404(template_id)
        data = request.get_json() or {}

        token = generate_token(6)
        while QueryTemplate.query.filter_by(share_token=token).first():
            token = generate_token(6)

        tpl.share_token = token
        expires_in = data.get('expires_in_hours', 24 * 7)
        if expires_in and expires_in > 0:
            tpl.share_expires_at = datetime.utcnow() + timedelta(hours=expires_in)
        tpl.share_access_count = 0
        db.session.commit()

        return jsonify({
            'token': token,
            'url': f'/share/template/{token}',
            'expires_at': tpl.share_expires_at.isoformat() if tpl.share_expires_at else None,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/share/template/<token>', methods=['GET'])
def get_shared_template(token):
    try:
        tpl = QueryTemplate.query.filter_by(share_token=token).first()
        if not tpl:
            return jsonify({'error': 'Invalid share token'}), 404
        if not tpl.is_share_valid():
            return jsonify({'error': 'Share link has expired'}), 404
        tpl.share_access_count += 1
        db.session.commit()
        return jsonify({'template': tpl.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# --- Plan snapshot and comparison routes ---

@api_bp.route('/plan/snapshots', methods=['GET'])
def list_plan_snapshots():
    try:
        template_id = request.args.get('template_id', type=int)
        limit = request.args.get('limit', default=50, type=int)
        query = PlanSnapshot.query
        if template_id:
            query = query.filter_by(template_id=template_id)
        snapshots = query.order_by(PlanSnapshot.created_at.desc()).limit(limit).all()
        return jsonify([s.to_dict() for s in snapshots])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/plan/snapshots/<int:snapshot_id>', methods=['GET'])
def get_plan_snapshot(snapshot_id):
    try:
        snap = PlanSnapshot.query.get_or_404(snapshot_id)
        return jsonify(snap.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@api_bp.route('/plan/snapshots', methods=['POST'])
def create_plan_snapshot():
    """Capture a snapshot for an arbitrary query structure without executing."""
    try:
        data = request.get_json() or {}
        query_structure = data.get('query_structure')
        if not query_structure:
            return jsonify({'error': 'query_structure is required'}), 400

        label = data.get('label')
        template_id = data.get('template_id')
        template_version = data.get('template_version')
        parameters = data.get('parameters', [])

        result = QueryExecutor.generate_sql(query_structure)
        sql = result['sql']
        params = result['params']

        from sqlalchemy import text as _text
        conn = db.engine.connect()
        try:
            plan_sql = f'EXPLAIN QUERY PLAN {sql}'
            plan_result = conn.execute(_text(plan_sql), params)
            raw_rows = [tuple(row) for row in plan_result.fetchall()]

            explain_sql = f'EXPLAIN {sql}'
            bytecode_result = conn.execute(_text(explain_sql), params)
            bytecode_rows = [tuple(row) for row in bytecode_result.fetchall()]
        finally:
            conn.close()

        snap_data = create_snapshot(
            query_structure=query_structure,
            raw_plan_rows=raw_rows,
            row_count=0,
            duration_ms=0,
            parameters=parameters,
            template_id=template_id,
            template_version=template_version,
            label=label,
        )
        snap = PlanSnapshot(**snap_data)
        db.session.add(snap)
        db.session.commit()
        return jsonify(snap.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/plan/compare', methods=['POST'])
def compare_plan_snapshots():
    """Compare two plan snapshots by ID or by AST structures."""
    try:
        data = request.get_json() or {}
        old_id = data.get('oldSnapshotId')
        new_id = data.get('newSnapshotId')

        if old_id and new_id:
            old_snap = PlanSnapshot.query.get_or_404(old_id)
            new_snap = PlanSnapshot.query.get_or_404(new_id)
            old_ops = old_snap.plan_operations
            new_ops = new_snap.plan_operations
        elif data.get('oldStructure') and data.get('newStructure'):
            old_qs = data['oldStructure']
            new_qs = data['newStructure']

            from sqlalchemy import text as _text
            old_sql_r = QueryExecutor.generate_sql(old_qs)
            new_sql_r = QueryExecutor.generate_sql(new_qs)

            conn = db.engine.connect()
            try:
                old_plan = conn.execute(
                    _text(f'EXPLAIN QUERY PLAN {old_sql_r["sql"]}'), old_sql_r['params']
                ).fetchall()
                new_plan = conn.execute(
                    _text(f'EXPLAIN QUERY PLAN {new_sql_r["sql"]}'), new_sql_r['params']
                ).fetchall()
            finally:
                conn.close()

            old_ops = normalize_explain_plan([tuple(r) for r in old_plan], old_qs)
            new_ops = normalize_explain_plan([tuple(r) for r in new_plan], new_qs)
        else:
            return jsonify({'error': 'Provide oldSnapshotId/newSnapshotId or oldStructure/newStructure'}), 400

        diff = diff_plans(old_ops, new_ops)
        return jsonify(diff)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/plan/compare/template/<int:template_id>', methods=['GET'])
def compare_template_versions(template_id):
    """Compare the two most recent snapshots for different versions of a template."""
    try:
        tpl = QueryTemplate.query.get_or_404(template_id)
        version_a = request.args.get('versionA', type=int)
        version_b = request.args.get('versionB', type=int)

        q = PlanSnapshot.query.filter_by(template_id=template_id)
        if version_a:
            snap_a = q.filter_by(template_version=version_a).order_by(
                PlanSnapshot.created_at.desc()).first()
        else:
            snap_a = q.order_by(PlanSnapshot.created_at.desc()).first()

        if version_b:
            snap_b = q.filter_by(template_version=version_b).order_by(
                PlanSnapshot.created_at.desc()).first()
        else:
            snap_b = q.filter(PlanSnapshot.id != snap_a.id if snap_a else True).order_by(
                PlanSnapshot.created_at.desc()).first()

        if not snap_a or not snap_b:
            return jsonify({'error': 'Need at least two snapshots to compare'}), 404

        diff = diff_plans(snap_a.plan_operations, snap_b.plan_operations)
        return jsonify({
            'oldSnapshot': snap_a.to_dict(),
            'newSnapshot': snap_b.to_dict(),
            'diff': diff,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# --- Batch run routes ---

@api_bp.route('/batches', methods=['POST'])
def create_batch():
    """Create and start a batch parameter run."""
    try:
        data = request.get_json() or {}
        template_id = data.get('template_id')
        if not template_id:
            return jsonify({'error': 'template_id is required'}), 400

        parameter_sets = data.get('parameter_sets')
        if not parameter_sets or not isinstance(parameter_sets, list):
            return jsonify({'error': 'parameter_sets must be a non-empty list'}), 400

        concurrency = data.get('concurrency', 1)
        max_total_rows = data.get('max_total_rows')
        max_duration_ms = data.get('max_duration_ms')
        idempotency_key = data.get('idempotency_key')
        label = data.get('label')

        batch, created = BatchService.create_batch(
            template_id=template_id,
            parameter_sets=parameter_sets,
            concurrency=concurrency,
            max_total_rows=max_total_rows,
            max_duration_ms=max_duration_ms,
            idempotency_key=idempotency_key,
            label=label,
        )

        if created:
            BatchService.start_batch(batch.id, app=current_app._get_current_object())

        result = batch.to_dict(include_items=True)
        status_code = 201 if created else 200
        return jsonify(result), status_code
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@api_bp.route('/batches', methods=['GET'])
def list_batches():
    try:
        template_id = request.args.get('template_id', type=int)
        limit = request.args.get('limit', default=50, type=int)
        batches = BatchService.list_batches(template_id=template_id, limit=limit)
        return jsonify([b.to_dict() for b in batches])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/batches/<int:batch_id>', methods=['GET'])
def get_batch(batch_id):
    try:
        batch = BatchService.get_batch(batch_id)
        include_items = request.args.get('items', 'true').lower() != 'false'
        return jsonify(batch.to_dict(include_items=include_items))
    except Exception as e:
        return jsonify({'error': str(e)}), 404

@api_bp.route('/batches/<int:batch_id>/cancel', methods=['POST'])
def cancel_batch(batch_id):
    try:
        batch = BatchService.cancel_batch(batch_id)
        return jsonify(batch.to_dict(include_items=True))
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@api_bp.route('/batches/<int:batch_id>/retry', methods=['POST'])
def retry_batch(batch_id):
    try:
        new_batch = BatchService.retry_failed(
            batch_id, app=current_app._get_current_object()
        )
        return jsonify(new_batch.to_dict(include_items=True)), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

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
            }
        }
    }
    return jsonify(spec)
