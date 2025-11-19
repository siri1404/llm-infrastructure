"""
Compliance Query API for audit logs.

Provides REST API for querying audit logs for regulatory compliance (SEC, FINRA).
"""

import logging
import os
from datetime import datetime
from flask import Flask, request, jsonify
from typing import Dict, Optional

from audit_logger import AuditLogger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize audit logger
audit_logger = AuditLogger()


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

