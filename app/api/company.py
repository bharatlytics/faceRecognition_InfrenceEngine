from flask import Blueprint, request, jsonify, abort, g
from db import employee_collection
from utils import validate_required_fields, error_response
from datetime import datetime
import functools
from bson import ObjectId

company_bp = Blueprint('company', __name__)
companies_collection = employee_collection.database['companies']

# --- Authentication Decorator (stub, replace with real auth) ---
def require_admin(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        # Example: check for a header or session (replace with real logic)
        if not request.headers.get('X-Admin-Token'):
            abort(401, description='Admin privileges required')
        return f(*args, **kwargs)
    return wrapper

# --- Company Model Builder ---
def build_company_doc(data):
    doc = {
        'companyName': data['companyName'],
        'createdAt': datetime.utcnow(),
        'lastUpdated': datetime.utcnow(),
        'status': data.get('status', 'active'),
        'logo': data.get('logo', ''),
        'colorScheme': {
            'primary': data.get('colorScheme', {}).get('primary', '#000000'),
            'secondary': data.get('colorScheme', {}).get('secondary', '#ffffff'),
            'accent': data.get('colorScheme', {}).get('accent', '#cccccc'),
            'background': data.get('colorScheme', {}).get('background', '#f0f0f0'),
            'text': data.get('colorScheme', {}).get('text', '#333333')
        },
        'hqAddress': data.get('hqAddress', ''),
        'hqEmail': data.get('hqEmail', ''),
        'website': data.get('website', ''),
        'phone': data.get('phone', ''),
        'designations': data.get('designations', []),
        'infrastructure': data.get('infrastructure', {}),
        'adminUsers': data.get('adminUsers', []),
    }
    return doc

@company_bp.route('', methods=['POST'])
def create_company():
    data = request.json or {}
    required_fields = ['companyName']
    valid, msg = validate_required_fields(data, required_fields)
    if not valid:
        return jsonify(error_response(msg, 400)), 400
    # Uniqueness check
    if companies_collection.find_one({'companyName': data['companyName']}):
        return jsonify(error_response('Company name already exists.', 409)), 409
    doc = build_company_doc(data)
    result = companies_collection.insert_one(doc)
    doc['_id'] = str(result.inserted_id)  # Convert ObjectId to string
    return jsonify({'message': 'Company created', 'company': doc}), 201

@company_bp.route('/seed', methods=['POST'])
def seed_company():
    data = {
        'companyName': 'Bhagwati Product Limited',
        'status': 'active',
        'logo': 'https://example.com/logo.png',
        'colorScheme': {
            'primary': '#0000ff',
            'secondary': '#ffffff',
            'accent': '#cccccc',
            'background': '#f0f0f0',
            'text': '#333333'
        },
        'hqAddress': '123 Main St, City, Country',
        'hqEmail': 'hq@bhagwati.com',
        'website': 'https://bhagwati.com',
        'phone': '1234567890',
        'designations': ['Manager', 'Engineer'],
        'infrastructure': {'type': 'Manufacturing'},
        'adminUsers': ['admin1', 'admin2']
    }
    existing_company = companies_collection.find_one({'companyName': data['companyName']})
    if existing_company:
        companies_collection.update_one(
            {'companyName': data['companyName']},
            {'$set': data}
        )
        doc = companies_collection.find_one({'companyName': data['companyName']})
        doc['_id'] = str(doc['_id'])  # Convert ObjectId to string
        return jsonify({'message': 'Company updated', 'company': doc}), 200
    else:
        doc = build_company_doc(data)
        result = companies_collection.insert_one(doc)
        doc['_id'] = str(result.inserted_id)  # Convert ObjectId to string
        return jsonify({'message': 'Company seeded', 'company': doc}), 201

@company_bp.route('', methods=['GET'])
def list_companies():
    # Optional: support search/filter
    query = {}
    name = request.args.get('name')
    status = request.args.get('status')
    if name:
        query['companyName'] = {'$regex': name, '$options': 'i'}
    if status:
        query['status'] = status
    
    # Get companies and transform _id to string
    companies = []
    for company in companies_collection.find(query):
        company['_id'] = str(company['_id'])  # Convert ObjectId to string
        companies.append(company)
    
    return jsonify({'companies': companies}), 200

@company_bp.route('/<company_id>', methods=['GET'])
def get_company(company_id):
    try:
        company = companies_collection.find_one({'_id': ObjectId(company_id)})
        if not company:
            return jsonify(error_response('Company not found', 404)), 404
        company['_id'] = str(company['_id'])  # Convert ObjectId to string
        return jsonify({'company': company}), 200
    except:
        return jsonify(error_response('Invalid company ID', 400)), 400

@company_bp.route('/<company_id>', methods=['PATCH'])
def update_company(company_id):
    try:
        data = request.json or {}
        company = companies_collection.find_one({'_id': ObjectId(company_id)})
        if not company:
            return jsonify(error_response('Company not found', 404)), 404
        
        update_fields = {}
        allowed_fields = ['companyName', 'status', 'logo', 'colorScheme', 'hqAddress', 'hqEmail', 'website', 'phone', 'designations', 'infrastructure', 'adminUsers']
        for field in allowed_fields:
            if field in data:
                update_fields[field] = data[field]
        
        if update_fields:
            update_fields['lastUpdated'] = datetime.utcnow()
            companies_collection.update_one({'_id': ObjectId(company_id)}, {'$set': update_fields})
        
        updated_company = companies_collection.find_one({'_id': ObjectId(company_id)})
        updated_company['_id'] = str(updated_company['_id'])  # Convert ObjectId to string
        return jsonify({'message': 'Company updated', 'company': updated_company}), 200
    except:
        return jsonify(error_response('Invalid company ID', 400)), 400

@company_bp.route('/<company_id>', methods=['DELETE'])
@require_admin
def delete_company(company_id):
    try:
        result = companies_collection.delete_one({'_id': ObjectId(company_id)})
        if result.deleted_count == 0:
            return jsonify(error_response('Company not found', 404)), 404
        return jsonify({'message': 'Company deleted successfully'}), 200
    except:
        return jsonify(error_response('Invalid company ID', 400)), 400

@company_bp.route('/<company_id>/designations', methods=['POST'])
def update_designations(company_id):
    data = request.json or {}
    designations = data.get('designations')
    if not isinstance(designations, list):
        return jsonify(error_response('Designations must be a list', 400)), 400
    result = companies_collection.update_one({'companyId': company_id}, {'$set': {'designations': designations, 'lastUpdated': datetime.utcnow()}})
    if result.matched_count == 0:
        return jsonify(error_response('Company not found', 404)), 404
    return jsonify({'message': 'Designations updated', 'designations': designations}), 200

@company_bp.route('/<company_id>/infrastructure', methods=['POST'])
def update_infrastructure(company_id):
    data = request.json or {}
    infrastructure = data.get('infrastructure')
    if not isinstance(infrastructure, dict):
        return jsonify(error_response('Infrastructure must be a dict', 400)), 400
    result = companies_collection.update_one({'companyId': company_id}, {'$set': {'infrastructure': infrastructure, 'lastUpdated': datetime.utcnow()}})
    if result.matched_count == 0:
        return jsonify(error_response('Company not found', 404)), 404
    return jsonify({'message': 'Infrastructure updated', 'infrastructure': infrastructure}), 200 