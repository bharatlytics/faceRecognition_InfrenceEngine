from datetime import datetime
from bson import ObjectId
from utils import get_current_utc

def build_employee_doc(data, image_dict, embeddings_dict):
    doc = {
        'employeeId': data['employeeId'],  # Keep if business field, not for MongoDB reference
        'employeeName': data['employeeName'],
        'companyId': ObjectId(data['companyId']),
        'employeeImages': image_dict,
        'employeeEmbeddings': embeddings_dict,
        'lastUpdated': get_current_utc(),
        'status': data.get('status', 'active'),
        'registrationDate': get_current_utc(),
        'blacklisted': data.get('blacklisted', False)
    }
    # Optional fields
    if data.get('gender'): doc['gender'] = data['gender']
    if data.get('joiningDate'): doc['joiningDate'] = parse_datetime(data['joiningDate'])
    if data.get('employeeEmail'): doc['employeeEmail'] = data['employeeEmail']
    if data.get('employeeMobile'): doc['employeeMobile'] = data['employeeMobile']
    if data.get('employeeDesignation'): doc['employeeDesignation'] = data['employeeDesignation']
    if data.get('employeeReportingId'): doc['employeeReportingId'] = data['employeeReportingId']
    return doc

def build_embedding_entry(embedding_id, corrupt=False):
    now = get_current_utc()
    return {
        'embeddingId': embedding_id,
        'createdAt': now,
        'updatedAt': now,
        'corrupt': corrupt
    }

def build_visitor_doc(data, image_dict, embeddings_dict, document_dict=None):
    doc = {
        'visitorName': data['visitorName'],
        'companyId': ObjectId(data['companyId']),
        'visitorImages': image_dict,
        'visitorEmbeddings': embeddings_dict,
        'visitorDocuments': document_dict or {},
        'lastUpdated': get_current_utc(),
        'status': data.get('status', 'active'),
        'registrationDate': get_current_utc(),
        'visitorType': data.get('visitorType', 'individual'),
        'idType': data.get('idType'),
        'idNumber': data.get('idNumber'),
        'phone': data.get('phone'),
        'email': data.get('email'),
        'organization': data.get('organization'),
        'purpose': data.get('purpose'),
        'hostEmployeeId': ObjectId(data['hostEmployeeId']) if data.get('hostEmployeeId') else None,
        'expectedArrival': parse_datetime(data.get('expectedArrival')) if data.get('expectedArrival') else None,
        'expectedDeparture': parse_datetime(data.get('expectedDeparture')) if data.get('expectedDeparture') else None,
        'blacklisted': data.get('blacklisted', False),
        'visits': []
    }
    return doc

def build_visit_doc(visitor_id, company_id, host_employee_id, purpose, expected_arrival, expected_departure, approved=False):
    return {
        'visitorId': visitor_id,
        'companyId': ObjectId(company_id),
        'hostEmployeeId': host_employee_id,
        'purpose': purpose,
        'status': 'scheduled',
        'expectedArrival': expected_arrival,  # Already parsed to UTC in schedule_visit
        'expectedDeparture': expected_departure,  # Already parsed to UTC in schedule_visit
        'actualArrival': None,
        'actualDeparture': None,
        'checkInMethod': None,
        'checkOutMethod': None,
        'createdAt': get_current_utc(),
        'lastUpdated': get_current_utc(),
        'qrCode': None,
        'accessAreas': [],
        'notes': [],
        'visitType': 'single',
        'approvedByHost': bool(approved)
    }

def build_entity_definition_doc(data):
    """Build an entity definition document that defines company-specific entity types and relationships."""
    # Validate the structure
    if not isinstance(data['structure'], dict):
        raise ValueError("Entity definition structure must be a dictionary")
    
    # Validate relationships
    if 'relationships' not in data or not isinstance(data['relationships'], list):
        raise ValueError("Entity definition must include valid relationships array")
    
    for rel in data['relationships']:
        if not all(k in rel for k in ['parentType', 'childType', 'cardinality']):
            raise ValueError("Each relationship must specify parentType, childType, and cardinality")
    
    doc = {
        'companyId': ObjectId(data['companyId']),
        'name': data['name'],
        'description': data.get('description', ''),
        'structure': {
            'entityTypes': data['structure'].get('entityTypes', {}),  # Dictionary of entity types and their metadata
            'allowedAttributes': data['structure'].get('allowedAttributes', {}),  # Dictionary of allowed attributes per type
            'validations': data['structure'].get('validations', {}),  # Dictionary of validation rules per type
        },
        'relationships': data['relationships'],  # Array of parent-child type relationships
        'status': data.get('status', 'active'),
        'templateRef': ObjectId(data['templateRef']) if data.get('templateRef') else None,  # Reference to source template if any
        'createdAt': get_current_utc(),
        'updatedAt': get_current_utc(),
        'version': data.get('version', '1.0')
    }
    return doc

def build_entity_doc(data):
    """Build an entity document with validation against entity definitions."""
    doc = {
        'name': data['name'],
        'type': data['type'],
        'definitionId': ObjectId(data['definitionId']),  # Reference to company's entity definition
        'companyId': ObjectId(data['companyId']),
        'parentId': ObjectId(data['parentId']) if data.get('parentId') else None,
        'path': data.get('path', []),
        'attributes': data.get('attributes', {}),
        'manager': {
            'employeeId': None,  # Reference to the employee document
            'assignedAt': None,  # Timestamp when assigned
            'status': 'vacant'   # Status: 'vacant' or 'filled'
        },
        'metadata': data.get('metadata', {}),
        'tags': data.get('tags', []),
        'status': data.get('status', 'active'),
        'createdAt': get_current_utc(),
        'updatedAt': get_current_utc()
    }
    return doc

def build_asset_doc(data, asset_type):
    """Build an asset document (employee, device, etc.)."""
    doc = {
        'name': data['name'],
        'type': asset_type,
        'entityId': ObjectId(data['entityId']),
        'orgId': ObjectId(data['orgId']),
        'metadata': data.get('metadata', {}),
        'createdAt': get_current_utc(),
        'updatedAt': get_current_utc(),
        'status': data.get('status', 'active')
    }
    return doc

def build_entity_template_doc(data):
    """Build an entity template document that serves as a base pattern."""
    doc = {
        'name': data['name'],
        'description': data.get('description', ''),
        'type': data['type'],
        'structure': {
            'entityTypes': data['structure']['entityTypes'],  # Base entity types (e.g., business_unit, plant, etc.)
            'defaultAttributes': data['structure'].get('defaultAttributes', {}),  # Default attributes for each type
            'defaultValidations': data['structure'].get('defaultValidations', {})  # Default validation rules
        },
        'relationships': data['relationships'],  # Base relationship rules
        'metadata': data.get('metadata', {}),
        'createdAt': get_current_utc(),
        'updatedAt': get_current_utc(),
        'version': data.get('version', '1.0'),
        'status': data.get('status', 'active')
    }
    return doc

def build_entity_clone_doc(template_entity, company_id, parent_id=None, name_prefix=''):
    """Build a cloned entity document from a template entity."""
    doc = {
        'name': name_prefix + template_entity['name'] if name_prefix else template_entity['name'],
        'type': template_entity['type'],
        'companyId': ObjectId(company_id),
        'parentId': ObjectId(parent_id) if parent_id else None,
        'metadata': template_entity.get('metadata', {}),
        'tags': template_entity.get('tags', []),
        'createdAt': get_current_utc(),
        'updatedAt': get_current_utc(),
        'templateRef': template_entity.get('_id'),  # Reference to original template
        'path': []  # Will be populated during creation
    }
    return doc 