from flask import Blueprint, request, jsonify, make_response
from app.services.metadata_service import MetadataService
from app.services.query_executor import QueryExecutor
from app.services.utils import generate_token, generate_export_sql
from app.models import SavedQuery, QueryHistory, db
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
            }
        }
    }
    return jsonify(spec)
