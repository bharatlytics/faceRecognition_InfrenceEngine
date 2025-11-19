from flask import Blueprint, request, jsonify, send_file, Response, g, abort, render_template
from db import employee_collection, employee_image_fs, embedding_jobs_collection
from models import build_employee_doc, build_embedding_entry
from embeddings import store_embedding, get_embedding_file
from utils import (
    get_optional_fields, error_response, update_embedding_status, validate_required_fields, validate_poses,
    validate_email_format, validate_phone_format, is_unique_email, is_unique_phone, fill_employee_fields,
    get_current_utc, parse_datetime, format_datetime
)
from constants import POSES
from app.config.config import Config
from datetime import datetime, timedelta, timezone
import threading
import queue
import time
import io
import bson
import base64
from pymongo import MongoClient
import functools
from collections import defaultdict
import re
from bson import ObjectId

employee_bp = Blueprint('employee', __name__)

audit_logs_collection = employee_collection.database['auditLogs']

# Helper to log audit events
def log_audit(action, employee_id, company_id, before, after):
    audit_logs_collection.insert_one({
        'user': getattr(g, 'user', 'system'),
        'timestamp': get_current_utc(),
        'action': action,
        'employeeId': employee_id,
        'companyId': company_id,
        'before': before,
        'after': after
    })

# --- Unicode Validation ---
UNICODE_EMAIL_REGEX = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', re.UNICODE)
def validate_email_format(email):
    return bool(UNICODE_EMAIL_REGEX.match(email))

def validate_name(name):
    # Allow any non-empty Unicode string
    return isinstance(name, str) and len(name.strip()) > 0

# --- Rate Limiting Middleware ---
RATE_LIMIT = 100  # requests
RATE_PERIOD = 60  # seconds
rate_limit_cache = defaultdict(list)

def log_security_event(event_type, ip, path):
    security_logs = employee_collection.database['securityLogs']
    security_logs.insert_one({
        'timestamp': get_current_utc(),
        'event': event_type,
        'ip': ip,
        'path': path
    })

def rate_limiter():
    ip = request.remote_addr
    now = time.time()
    window = now - RATE_PERIOD
    rate_limit_cache[ip] = [t for t in rate_limit_cache[ip] if t > window]
    if len(rate_limit_cache[ip]) >= RATE_LIMIT:
        log_security_event('rate_limit', ip, request.path)
        abort(429, description='Too Many Requests')
    rate_limit_cache[ip].append(now)

# --- Authentication Decorator (stub, replace with real auth) ---
def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        # Example: check for a header or session (replace with real logic)
        if not request.headers.get('X-Auth-Token'):
            log_security_event('unauthorized', request.remote_addr, request.path)
            abort(401, description='Unauthorized')
        return f(*args, **kwargs)
    return wrapper

@employee_bp.before_request
def before_request():
    rate_limiter()

@employee_bp.route('/register', methods=['POST'])
def register_employee():
    try:
        required_fields = ['employeeId', 'employeeName', 'companyId']
        valid, msg = validate_required_fields(request.form, required_fields)
        if not valid:
            return error_response(msg, 400)
        valid, msg = validate_poses(request.files)
        if not valid:
            return error_response(msg, 400)
        data = {field: request.form[field] for field in required_fields}
        optional_fields = [
            'gender', 'joiningDate', 'employeeEmail', 'employeeMobile',
            'employeeDesignation', 'employeeReportingId', 'status', 'blacklisted'
        ]
        data.update(get_optional_fields(request.form, optional_fields))
        data['blacklisted'] = data.get('blacklisted', 'false').lower() == 'true'
        # Email/phone validation and uniqueness
        if data.get('employeeEmail'):
            if not validate_email_format(data['employeeEmail']):
                return error_response('Invalid email format.', 400)
            if not is_unique_email(employee_collection, data['companyId'], data['employeeEmail'], exclude_employee_id=data['employeeId']):
                return error_response('Email must be unique within the company.', 409)
        if data.get('employeeMobile'):
            if not validate_phone_format(data['employeeMobile']):
                return error_response('Invalid phone number format. Must be 10 digits.', 400)
            if not is_unique_phone(employee_collection, data['companyId'], data['employeeMobile'], exclude_employee_id=data['employeeId']):
                return error_response('Phone number must be unique within the company.', 409)
        existing = employee_collection.find_one({'companyId': data['companyId'], 'employeeId': data['employeeId']})
        if existing:
            buffalo_status = existing.get('employeeEmbeddings', {}).get('buffalo_l', {}).get('status')
            emp_status = existing.get('status')
            # Only block if status is 'done' or 'active' (treat 'done' as active)
            if buffalo_status in ['done', 'active'] or emp_status in ['active']:
                return error_response('Employee with this ID already exists in the company and is active.', 409)
            # Block registration if status is 'pending_duplicate_removal'
            if emp_status == 'pending_duplicate_removal':
                return error_response('Duplicate employee cannot be re-registered as active. Please contact admin or cleanup duplicates.', 409)
        embedding_attached = request.form.get('embeddingAttached', 'false').lower() == 'true'
        embedding_version = request.form.get('embeddingVersion')
        embeddings_dict = {}
        image_dict = {}
        
        # Simplified image validation and storage
        for pose in POSES:
            file = request.files[pose]
            if not file:
                return error_response(f'Missing image for pose: {pose}', 400)
            
            # Basic image validation - just check if there's content
            img_bytes = file.read()
            if not img_bytes:
                return error_response(f'Empty image file for pose: {pose}', 400)
                
            # Store the image directly
            image_id = employee_image_fs.put(img_bytes, filename=f"{data['companyId']}_{data['employeeId']}_{pose}.jpg", metadata={
                'companyId': data['companyId'],
                'employeeId': data['employeeId'],
                'pose': pose,
                'type': 'image',
                'timestamp': get_current_utc()
            })
            image_dict[pose] = image_id

        # Build and insert employee document
        employee_doc = build_employee_doc(data, image_dict, embeddings_dict)
        result = employee_collection.update_one(
            {'companyId': ObjectId(data['companyId']), 'employeeId': data['employeeId']},
            {'$set': employee_doc},
            upsert=True
        )
        # Fetch the employee document to get its _id
        employee = employee_collection.find_one({'companyId': ObjectId(data['companyId']), 'employeeId': data['employeeId']})
        employee_object_id = employee['_id']
        for model in Config.ALLOWED_MODELS:
            model_status = employee.get('employeeEmbeddings', {}).get(model, {}).get('status') if employee else None
            if model_status not in ['queued', 'started', 'inprogress', 'done', 'active']:
                job = {
                    "employeeId": employee_object_id,
                    "companyId": ObjectId(data['companyId']),
                    "model": model,
                    "status": "queued",
                    "createdAt": get_current_utc(),
                    "params": {}
                }
                embedding_jobs_collection.insert_one(job)
                embeddings_dict[model] = {'status': 'queued', 'queuedAt': get_current_utc()}
            else:
                if employee and 'employeeEmbeddings' in employee and model in employee['employeeEmbeddings']:
                    embeddings_dict[model] = employee['employeeEmbeddings'][model]
        if embedding_attached:
            if not embedding_version or 'embedding' not in request.files:
                return error_response('embeddingVersion and embedding file required when embeddingAttached is true')
            if embedding_version not in Config.ALLOWED_MODELS:
                return error_response('Embedding model not allowed.', 400)
            embedding_file = request.files['embedding']
            try:
                # Store the file content as-is
                file_content = embedding_file.read()
                embedding_filename = embedding_file.filename  # Use the original filename and extension
                embedding_metadata = {
                    'companyId': data['companyId'],
                    'employeeId': data['employeeId'],
                    'model': embedding_version,
                    'type': 'embedding',
                    'timestamp': get_current_utc()
                }
                # Store the raw file content
                emb_entry = store_embedding(file_content, embedding_filename, embedding_metadata, embedding_version)
                emb_entry['status'] = 'done'
                emb_entry['finishedAt'] = get_current_utc()
                embeddings_dict[embedding_version] = emb_entry
                # Update the employee document with the new embedding entry
                employee_collection.update_one(
                    {'companyId': ObjectId(data['companyId']), 'employeeId': data['employeeId']},
                    {'$set': {f'employeeEmbeddings.{embedding_version}': emb_entry}}
                )
            except Exception as e:
                employee_collection.update_one(
                    {'companyId': data['companyId'], 'employeeId': data['employeeId']},
                    {'$set': {'status': 'incomplete', 'lastUpdated': get_current_utc()}},
                    upsert=True
                )
                return error_response(f'Error storing embedding: {e}', 400)
        print("Embeddings dict to be saved:", embeddings_dict)
        before = existing if existing else None
        after = employee_doc
        log_audit('register', data['employeeId'], data['companyId'], before, after)
        return jsonify({'message': 'Employee registration queued', 'employeeId': data['employeeId'], 'embeddingStatus': {k: v.get('status', 'unknown') for k, v in embeddings_dict.items()}}), 200
    except Exception as e:
        print(f"Error in register_employee: {e}")
        return error_response(str(e), 500)

@employee_bp.route('/', methods=['GET'])
def get_employee():
    try:
        company_id = request.args.get('companyId')
        if not company_id:
            return error_response('companyId is required', 400)
            
        print(f"Fetching employees for companyId: {company_id}")
        
        employee_id = request.args.get('employeeId')
        fetch_embeddings = request.args.get('fetchEmbeddings', 'false').lower() == 'true'
        embedding_version = request.args.get('embeddingVersion')
        fetch_images = request.args.get('fetchImages', 'false').lower() == 'true'
        fields = request.args.get('fields')
        field_list = [f.strip() for f in fields.split(',')] if fields else None

        query = {'companyId': ObjectId(company_id)}  # Convert string companyId to ObjectId
        if employee_id:
            query['employeeId'] = employee_id
        query['status'] = {'$ne': 'archived'}
        
        print(f"Query: {query}")
        
        employees = list(employee_collection.find(query))
        print(f"Found {len(employees)} employees")
        
        # Always use the correct API prefix for URLs
        base_url = request.url_root.rstrip('/') + '/bharatlytics/v1'
        
        results = []
        for employee in employees:
            # Convert ObjectId to string in the employee document
            employee['_id'] = str(employee['_id'])
            employee['companyId'] = str(employee['companyId'])
            
            result = fill_employee_fields(employee)
            # Add requested fields (if fields param is used, filter to only those)
            if field_list:
                result = {k: v for k, v in result.items() if k in field_list or k in ['employeeId', 'companyId']}
            # Images
            if fetch_images:
                result['employeeImages'] = {}
                for pose, img_id in employee.get('employeeImages', {}).items():
                    result['employeeImages'][pose] = f"{base_url}/employees/images/{img_id}"
            # Embeddings
            if fetch_embeddings:
                result['employeeEmbeddings'] = {}
                emb_dict = employee.get('employeeEmbeddings', {})
                print(f"Employee {employee.get('employeeId')} embeddings: {emb_dict}")
                if embedding_version:
                    emb = emb_dict.get(embedding_version)
                    if emb and emb.get('embeddingId'):
                        result['employeeEmbeddings'][embedding_version] = {
                            'downloadUrl': f"{base_url}/employees/embeddings/{emb['embeddingId']}",
                            'status': emb.get('status', 'unknown'),
                            'createdAt': emb.get('createdAt'),
                            'finishedAt': emb.get('finishedAt')
                        }
                else:
                    for model, emb in emb_dict.items():
                        if emb.get('embeddingId'):
                            result['employeeEmbeddings'][model] = {
                                'downloadUrl': f"{base_url}/employees/embeddings/{emb['embeddingId']}",
                                'status': emb.get('status', 'unknown'),
                                'createdAt': emb.get('createdAt'),
                                'finishedAt': emb.get('finishedAt')
                            }
            results.append(result)
            
        print(f"Returning {len(results)} results")
        return jsonify(results), 200
    except Exception as e:
        print(f"Error in get_employee: {e}")
        return error_response(str(e), 500)

@employee_bp.route('/images/<image_id>', methods=['GET'])
def serve_employee_image(image_id):
    try:
        file = employee_image_fs.get(bson.ObjectId(image_id))
        return Response(file.read(), mimetype='image/jpeg', headers={
            'Content-Disposition': f'inline; filename={image_id}.jpg'
        })
    except Exception as e:
        print(f"Error serving image {image_id}: {e}")
        return error_response('Image not found', 404)

@employee_bp.route('/embeddings/<embedding_id>', methods=['GET'])
def serve_employee_embedding(embedding_id):
    try:
        from db import employee_embedding_fs
        print(f"Attempting to fetch embedding: {embedding_id}")
        try:
            file = employee_embedding_fs.get(bson.ObjectId(embedding_id))
            print(f"Successfully found embedding file")
            # Get the original filename and extension
            filename = file.filename if hasattr(file, 'filename') else f"{embedding_id}"
            if filename.endswith('.pkl'):
                mimetype = 'application/octet-stream'
            elif filename.endswith('.txt'):
                mimetype = 'text/plain'
            else:
                mimetype = 'application/octet-stream'
            return Response(
                file.read(),
                mimetype=mimetype,
                headers={
                    'Content-Disposition': f'inline; filename={filename}'
                }
            )
        except bson.errors.InvalidId:
            print(f"Invalid embedding ID format: {embedding_id}")
            return error_response('Invalid embedding ID format', 400)
        except Exception as e:
            print(f"Error fetching embedding file: {e}")
            return error_response('Embedding not found', 404)
    except Exception as e:
        print(f"Error in serve_employee_embedding: {e}")
        return error_response('Error serving embedding', 500)

@employee_bp.route('/update', methods=['PATCH'])
def update_employee():
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        required_fields = ['employeeId', 'companyId']
        valid, msg = validate_required_fields(data, required_fields)
        if not valid:
            return error_response(msg, 400)
        employee_id = data['employeeId']
        company_id = data['companyId']
        # Prevent status update for duplicates
        employee = employee_collection.find_one({'companyId': company_id, 'employeeId': employee_id})
        if employee:
            buffalo_status = employee.get('employeeEmbeddings', {}).get('buffalo_l', {}).get('status')
            emp_status = employee.get('status')
            if buffalo_status == 'duplicate' or emp_status == 'pending_duplicate_removal':
                if 'status' in data or ('status' in data and data['status'] != 'pending_duplicate_removal'):
                    return error_response('Cannot update status of a duplicate employee. Please contact admin or cleanup duplicates.', 409)
        update_fields = {}
        for key in ['employeeName', 'gender', 'blacklisted', 'joiningDate', 'status', 'employeeEmail', 'employeeMobile', 'employeeDesignation', 'employeeReportingId']:
            if key in data:
                value = data[key]
                if key == 'blacklisted':
                    value = value.lower() == 'true' if isinstance(value, str) else bool(value)
                update_fields[key] = value
        # Email/phone validation and uniqueness on update
        if 'employeeEmail' in update_fields:
            if not validate_email_format(update_fields['employeeEmail']):
                return error_response('Invalid email format.', 400)
            if not is_unique_email(employee_collection, company_id, update_fields['employeeEmail'], exclude_employee_id=employee_id):
                return error_response('Email must be unique within the company.', 409)
        if 'employeeMobile' in update_fields:
            if not validate_phone_format(update_fields['employeeMobile']):
                return error_response('Invalid phone number format. Must be 10 digits.', 400)
            if not is_unique_phone(employee_collection, company_id, update_fields['employeeMobile'], exclude_employee_id=employee_id):
                return error_response('Phone number must be unique within the company.', 409)
        update_fields['lastUpdated'] = get_current_utc()
        result = employee_collection.update_one(
            {'companyId': company_id, 'employeeId': employee_id},
            {'$set': update_fields}
        )
        if result.matched_count == 0:
            return error_response('Employee not found', 404)
        print(f"Employee {employee_id} in {company_id} updated: {update_fields}")
        before = employee
        after = employee_collection.find_one({'companyId': company_id, 'employeeId': employee_id})
        log_audit('update', employee_id, company_id, before, after)
        return jsonify({'message': 'Employee updated successfully'}), 200
    except Exception as e:
        print(f"Error in update_employee: {e}")
        return error_response(str(e), 500)

@employee_bp.route('/delete', methods=['DELETE'])
def delete_employee():
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        required_fields = ['employeeId', 'companyId']
        valid, msg = validate_required_fields(data, required_fields)
        if not valid:
            return error_response(msg, 400)
        employee_id = data['employeeId']
        company_id = data['companyId']
        mode = data.get('mode', 'soft').lower()  # 'soft' or 'hard'
        reason = data.get('reason', 'user_request')
        employee = employee_collection.find_one({'companyId': company_id, 'employeeId': employee_id})
        if not employee:
            return error_response('Employee not found', 404)
        if mode == 'soft':
            # Soft delete: mark as archived
            update_fields = {
                'status': 'archived',
                'deletedAt': get_current_utc(),
                'deletedReason': reason
            }
            employee_collection.update_one(
                {'companyId': company_id, 'employeeId': employee_id},
                {'$set': update_fields}
            )
            print(f"Soft deleted employee {employee_id} in {company_id} (reason: {reason})")
            before = employee
            after = None
            log_audit('delete', employee_id, company_id, before, after)
            return jsonify({'message': 'Employee soft deleted (archived) successfully'}), 200
        elif mode == 'hard':
            # Hard delete: remove from DB and optionally GridFS
            # Remove images from GridFS
            image_dict = employee.get('employeeImages', {})
            for img_id in image_dict.values():
                try:
                    employee_image_fs.delete(img_id)
                except Exception as e:
                    print(f"Warning: Could not delete image {img_id} from GridFS: {e}")
            # Remove embeddings from GridFS
            for emb in employee.get('employeeEmbeddings', {}).values():
                emb_id = emb.get('embeddingId')
                if emb_id:
                    try:
                        from db import employee_embedding_fs
                        employee_embedding_fs.delete(emb_id)
                    except Exception as e:
                        print(f"Warning: Could not delete embedding {emb_id} from GridFS: {e}")
            # Remove from DB
            employee_collection.delete_one({'companyId': company_id, 'employeeId': employee_id})
            print(f"Hard deleted employee {employee_id} in {company_id}")
            before = employee
            after = None
            log_audit('delete', employee_id, company_id, before, after)
            return jsonify({'message': 'Employee hard deleted successfully'}), 200
        else:
            return error_response('Invalid delete mode. Use "soft" or "hard".', 400)
    except Exception as e:
        print(f"Error in delete_employee: {e}")
        return error_response(str(e), 500)

@employee_bp.route('/cleanup-duplicates', methods=['POST'])
def cleanup_duplicates():
    try:
        # Get required companyId parameter
        company_id = request.form.get('companyId')
        if not company_id:
            return error_response('companyId is required', 400)
            
        # Get hours parameter from request, default to 24 if not provided
        hours = int(request.form.get('hours', 24))
        
        # Validate hours parameter
        if hours < 1 or hours > 168:  # Max 1 week
            return error_response('Hours must be between 1 and 168', 400)
            
        cutoff = get_current_utc() - timedelta(hours=hours)
        to_delete = employee_collection.find({
            "companyId": company_id,  # Add companyId filter
            "status": "pending_duplicate_removal",
            "employeeEmbeddings.buffalo_l.finishedAt": {"$lt": cutoff}
        })
        
        count = 0
        for emp in to_delete:
            print(f"[Cleanup] Deleting employee {emp['employeeId']} in {emp['companyId']} (pending_duplicate_removal > {hours}h)")
            employee_collection.delete_one({"_id": emp["_id"]})
            count += 1
            
        return jsonify({
            'message': f'Successfully cleaned up {count} duplicate employees',
            'deleted_count': count,
            'hours_threshold': hours,
            'companyId': company_id
        }), 200
        
    except Exception as e:
        print(f"Error in cleanup_duplicates: {e}")
        return error_response(str(e), 500)

@employee_bp.route('/audit-logs', methods=['GET'])
@require_auth
def get_audit_logs():
    # Only allow admin (add your own admin check here)
    # if not g.user_is_admin:
    #     return error_response('Forbidden', 403)
    employee_id = request.args.get('employeeId')
    company_id = request.args.get('companyId')
    query = {}
    if employee_id:
        query['employeeId'] = employee_id
    if company_id:
        query['companyId'] = company_id
    logs = list(audit_logs_collection.find(query).sort('timestamp', -1))
    for log in logs:
        log['_id'] = str(log['_id'])
        log['timestamp'] = format_datetime(log['timestamp'])
    return jsonify(logs), 200

@employee_bp.route('/employees/page', methods=['GET'])
def employee_page():
    return render_template('employees.html') 