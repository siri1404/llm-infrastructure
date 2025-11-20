"""
Compliance Query API for audit logs.

Provides REST API for querying audit logs for regulatory compliance:
- SEC (Securities and Exchange Commission)
- FINRA (Financial Industry Regulatory Authority)
- MiFID II (Markets in Financial Instruments Directive)
- GDPR (General Data Protection Regulation)
- CCPA (California Consumer Privacy Act)
"""

import logging
import os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from functools import wraps
from typing import Dict, Optional
import hashlib
import hmac

try:
    from audit_logger import AuditLogger
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from audit_logger import AuditLogger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize audit logger
audit_logger = AuditLogger()

# Authorization configuration
# In production, use environment variables or secure secret management
API_KEY_HASH = os.getenv('COMPLIANCE_API_KEY_HASH', hashlib.sha256('dev-secret-key'.encode()).hexdigest())
REQUIRE_AUTHORIZATION = os.getenv('REQUIRE_AUTHORIZATION', 'true').lower() == 'true'


def verify_api_key(provided_key: str) -> bool:
    """
    Verify API key against stored hash.
    
    Args:
        provided_key: The API key provided in the request
        
    Returns:
        True if valid, False otherwise
    """
    if not provided_key:
        return False
    provided_hash = hashlib.sha256(provided_key.encode()).hexdigest()
    return hmac.compare_digest(provided_hash, API_KEY_HASH)


def verify_tenant_access(api_key: str, tenant_id: str) -> bool:
    """
    Verify that the API key has access to the specified tenant.
    
    In production, this should query a database or authorization service.
    For now, we implement a simple check.
    
    Args:
        api_key: The authenticated API key
        tenant_id: The tenant ID being accessed
        
    Returns:
        True if authorized, False otherwise
    """
    # TODO: Implement proper tenant-to-key mapping
    # For now, valid API key = access to all tenants
    return verify_api_key(api_key)


def require_authorization(f):
    """
    Decorator to require API key authorization for sensitive endpoints.
    
    Expects Authorization header with format: "Bearer <api-key>"
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not REQUIRE_AUTHORIZATION:
            logger.warning("Authorization is disabled! Enable REQUIRE_AUTHORIZATION in production.")
            return f(*args, **kwargs)
        
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            logger.warning(f"Unauthorized access attempt to {request.path} - No authorization header")
            return jsonify({
                "error": "Authorization required",
                "message": "Please provide an API key in the Authorization header (Bearer <api-key>)"
            }), 401
        
        # Parse Bearer token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            logger.warning(f"Unauthorized access attempt to {request.path} - Invalid authorization format")
            return jsonify({
                "error": "Invalid authorization format",
                "message": "Use: Authorization: Bearer <api-key>"
            }), 401
        
        api_key = parts[1]
        
        if not verify_api_key(api_key):
            logger.warning(f"Unauthorized access attempt to {request.path} - Invalid API key")
            return jsonify({
                "error": "Invalid API key",
                "message": "The provided API key is not valid"
            }), 403
        
        # Store the API key in request context for tenant verification
        request.api_key = api_key
        
        logger.info(f"Authorized access to {request.path}")
        return f(*args, **kwargs)
    
    return decorated_function


def log_deletion_request(user_id: str, tenant_id: Optional[str], requester_info: Dict):
    """
    Log GDPR deletion requests for audit trail.
    
    Args:
        user_id: The user whose data is being deleted
        tenant_id: Optional tenant ID
        requester_info: Information about who requested the deletion
    """
    logger.info(
        f"GDPR DELETION REQUEST: user_id={user_id}, tenant_id={tenant_id}, "
        f"endpoint={request.path}, ip={request.remote_addr}"
    )
    
    # In production, log to a separate deletion audit log
    try:
        # Could store in a dedicated deletion_audit table
        deletion_metadata = {
            'action': 'gdpr_deletion_request',
            'user_id': user_id,
            'tenant_id': tenant_id,
            'requester_ip': request.remote_addr,
            'timestamp': datetime.utcnow().isoformat(),
            'endpoint': request.path
        }
        # Additional audit logging can be implemented here
    except Exception as e:
        logger.error(f"Failed to log deletion request: {e}")





@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "compliance-api"}), 200


@app.route('/api/compliance/query', methods=['POST'])
def compliance_query():
    """
    Query audit logs for compliance purposes.
    
    Request body (JSON):
    {
        "request_id": "uuid",              # Optional: exact request ID
        "input_hash": "sha256_hash",       # Optional: find duplicates
        "tenant_id": "financial-firm-123", # Optional: filter by tenant
        "user_id": "user-456",             # Optional: filter by user
        "source": "earnings-report",       # Optional: filter by source
        "status": "success",               # Optional: success/error
        "start_time": "2025-01-15T00:00:00Z", # Optional: start timestamp
        "end_time": "2025-01-16T00:00:00Z",  # Optional: end timestamp
        "limit": 100                       # Optional: max results (default: 100)
    }
    
    Returns:
        List of audit log entries matching criteria
    """
    try:
        query_params = request.json or {}
        
        # Validate and convert query parameters
        filters = {}
        
        if 'request_id' in query_params:
            filters['request_id'] = query_params['request_id']
        
        if 'input_hash' in query_params:
            filters['input_hash'] = query_params['input_hash']
        
        if 'tenant_id' in query_params:
            filters['tenant_id'] = query_params['tenant_id']
        
        if 'user_id' in query_params:
            filters['user_id'] = query_params['user_id']
        
        if 'source' in query_params:
            filters['source'] = query_params['source']
        
        if 'status' in query_params:
            if query_params['status'] not in ['success', 'error']:
                return jsonify({"error": "status must be 'success' or 'error'"}), 400
            filters['status'] = query_params['status']
        
        if 'start_time' in query_params:
            filters['start_time'] = query_params['start_time']
        
        if 'end_time' in query_params:
            filters['end_time'] = query_params['end_time']
        
        if 'limit' in query_params:
            filters['limit'] = int(query_params['limit'])
        
        # Execute query
        results = audit_logger.query_logs(filters)
        
        return jsonify({
            "count": len(results),
            "results": results
        }), 200
        
    except Exception as e:
        logger.error(f"Error in compliance query: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/compliance/request/<request_id>', methods=['GET'])
def get_request(request_id: str):
    """
    Get specific audit log entry by request ID.
    
    Args:
        request_id: Request ID to lookup
        
    Returns:
        Audit log entry or 404 if not found
    """
    try:
        results = audit_logger.query_logs({'request_id': request_id, 'limit': 1})
        
        if not results:
            return jsonify({"error": "Request not found"}), 404
        
        return jsonify(results[0]), 200
        
    except Exception as e:
        logger.error(f"Error getting request: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/compliance/duplicates/<input_hash>', methods=['GET'])
def get_duplicates(input_hash: str):
    """
    Find all requests with the same input (by hash).
    
    Useful for finding duplicate processing or tracking document versions.
    
    Args:
        input_hash: SHA256 hash of input text
        
    Returns:
        List of audit log entries with same input hash
    """
    try:
        results = audit_logger.query_logs({'input_hash': input_hash})
        
        return jsonify({
            "count": len(results),
            "input_hash": input_hash,
            "results": results
        }), 200
        
    except Exception as e:
        logger.error(f"Error finding duplicates: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/compliance/statistics', methods=['GET'])
def get_statistics():
    """
    Get audit log statistics.
    
    Returns:
        Statistics about audit logs
    """
    try:
        stats = audit_logger.get_statistics()
        return jsonify(stats), 200
        
    except Exception as e:
        logger.error(f"Error getting statistics: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/compliance/prebuilt/sec', methods=['POST'])
def sec_compliance_query():
    """
    Prebuilt SEC compliance query.
    
    SEC requirements:
    - Complete audit trail of all transactions
    - Request deduplication
    - Time-range queries for reporting periods
    
    Request body (JSON):
    {
        "start_date": "2025-01-01",  # Start date (YYYY-MM-DD)
        "end_date": "2025-01-31",    # End date (YYYY-MM-DD)
        "tenant_id": "firm-123"      # Optional: filter by firm
    }
    """
    try:
        params = request.json or {}
        start_date = params.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
        end_date = params.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        
        filters = {
            'start_time': f"{start_date}T00:00:00Z",
            'end_time': f"{end_date}T23:59:59Z",
            'limit': params.get('limit', 10000)
        }
        
        if 'tenant_id' in params:
            filters['tenant_id'] = params['tenant_id']
        
        results = audit_logger.query_logs(filters)
        
        return jsonify({
            "compliance_standard": "SEC",
            "reporting_period": f"{start_date} to {end_date}",
            "count": len(results),
            "results": results
        }), 200
        
    except Exception as e:
        logger.error(f"Error in SEC compliance query: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/compliance/prebuilt/finra', methods=['POST'])
def finra_compliance_query():
    """
    Prebuilt FINRA compliance query.
    
    FINRA requirements:
    - Complete request/response logging
    - Error tracking and reporting
    - Export capabilities for audits
    
    Request body (JSON):
    {
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
        "include_errors": true  # Include error logs
    }
    """
    try:
        params = request.json or {}
        start_date = params.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
        end_date = params.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        include_errors = params.get('include_errors', True)
        
        filters = {
            'start_time': f"{start_date}T00:00:00Z",
            'end_time': f"{end_date}T23:59:59Z",
            'limit': params.get('limit', 10000)
        }
        
        if not include_errors:
            filters['status'] = 'success'
        
        results = audit_logger.query_logs(filters)
        
        return jsonify({
            "compliance_standard": "FINRA",
            "reporting_period": f"{start_date} to {end_date}",
            "include_errors": include_errors,
            "count": len(results),
            "results": results
        }), 200
        
    except Exception as e:
        logger.error(f"Error in FINRA compliance query: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/compliance/prebuilt/mifid2', methods=['POST'])
def mifid2_compliance_query():
    """
    Prebuilt MiFID II compliance query.
    
    MiFID II requirements:
    - Transaction reporting
    - Explainability for algorithmic trading decisions
    - Model version tracking
    
    Request body (JSON):
    {
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
        "require_explanations": true  # Only include requests with explanations
    }
    """
    try:
        params = request.json or {}
        start_date = params.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
        end_date = params.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        require_explanations = params.get('require_explanations', False)
        
        filters = {
            'start_time': f"{start_date}T00:00:00Z",
            'end_time': f"{end_date}T23:59:59Z",
            'limit': params.get('limit', 10000)
        }
        
        results = audit_logger.query_logs(filters)
        
        # Filter for explanations if required
        if require_explanations:
            results = [r for r in results if r.get('explanation')]
        
        return jsonify({
            "compliance_standard": "MiFID II",
            "reporting_period": f"{start_date} to {end_date}",
            "require_explanations": require_explanations,
            "count": len(results),
            "results": results
        }), 200
        
    except Exception as e:
        logger.error(f"Error in MiFID II compliance query: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/compliance/prebuilt/gdpr', methods=['POST'])
@require_authorization
def gdpr_compliance_query():
    """
    Prebuilt GDPR compliance query.
    
    GDPR requirements:
    - Right to access: Get all data for a user
    - Right to deletion: Delete user data
    - Data portability: Export user data
    
    Request body (JSON):
    {
        "user_id": "user-123",
        "tenant_id": "tenant-abc",  # Optional
        "action": "access"  # "access", "delete", or "export"
    }
    """
    try:
        params = request.json or {}
        user_id = params.get('user_id')
        tenant_id = params.get('tenant_id')
        action = params.get('action', 'access')
        
        if not user_id:
            return jsonify({"error": "user_id is required for GDPR queries"}), 400
        
        if action == 'delete':
            # GDPR Right to Deletion
            # Verify tenant access if tenant_id provided
            if tenant_id and hasattr(request, "api_key"):
                if not verify_tenant_access(request.api_key, tenant_id):
                    logger.warning(f"Unauthorized tenant access: user_id={user_id}, tenant_id={tenant_id}")
                    return jsonify({
                        "error": "Unauthorized",
                        "message": "No permission to delete data for this tenant"
                    }), 403
            
            # Log the deletion request
            log_deletion_request(user_id, tenant_id, {
                "api_key_used": hasattr(request, "api_key"),
                "ip_address": request.remote_addr
            })
            
            deleted_count = audit_logger.delete_user_data(user_id, tenant_id)
            return jsonify({
                "compliance_standard": "GDPR",
                "action": "deletion",
                "user_id": user_id,
                "records_deleted": deleted_count
            }), 200
        
        # GDPR Right to Access / Data Portability
        filters = {
            'user_id': user_id,
            'limit': 10000
        }
        
        if tenant_id:
            filters['tenant_id'] = tenant_id
        
        results = audit_logger.query_logs(filters)
        
        return jsonify({
            "compliance_standard": "GDPR",
            "action": action,
            "user_id": user_id,
            "count": len(results),
            "results": results
        }), 200
        
    except Exception as e:
        logger.error(f"Error in GDPR compliance query: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/compliance/export', methods=['POST'])
def export_logs():
    """
    Export audit logs in CSV format for compliance reporting.
    
    Request body (JSON):
    {
        "start_time": "2025-01-15T00:00:00Z",
        "end_time": "2025-01-16T00:00:00Z",
        "format": "csv"  # Currently only CSV supported
    }
    
    Returns:
        CSV file download
    """
    try:
        query_params = request.json or {}
        
        filters = {}
        if 'start_time' in query_params:
            filters['start_time'] = query_params['start_time']
        if 'end_time' in query_params:
            filters['end_time'] = query_params['end_time']
        
        # Get all matching logs (no limit for export)
        filters['limit'] = 10000  # Large limit for export
        results = audit_logger.query_logs(filters)
        
        # Generate CSV
        import csv
        import io
        
        output = io.StringIO()
        if results:
            fieldnames = results[0].keys()
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        csv_data = output.getvalue()
        output.close()
        
        from flask import Response
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=audit_logs_{datetime.utcnow().strftime("%Y%m%d")}.csv'
            }
        )
        
    except Exception as e:
        logger.error(f"Error exporting logs: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('COMPLIANCE_API_PORT', 5000))
    host = os.getenv('COMPLIANCE_API_HOST', '0.0.0.0')
    
    logger.info(f"Starting Compliance API on {host}:{port}")
    logger.info("Endpoints:")
    logger.info("  POST /api/compliance/query - Query audit logs")
    logger.info("  GET  /api/compliance/request/<id> - Get specific request")
    logger.info("  GET  /api/compliance/duplicates/<hash> - Find duplicates")
    logger.info("  GET  /api/compliance/statistics - Get statistics")
    logger.info("  POST /api/compliance/export - Export logs to CSV")
    
    app.run(host=host, port=port, debug=False)

