from flask import Blueprint, request, jsonify
from bson import ObjectId, json_util
import json
import db
from functools import wraps

# Access collections through the db module
entity_collection = db.entity_collection
asset_collection = db.asset_collection
employee_collection = db.employee_collection
company_collection = db.company_collection
entity_template_collection = db.entity_template_collection
entity_definition_collection = db.entity_definition_collection

from models import (
    build_entity_doc, build_asset_doc,
    build_entity_template_doc, build_entity_definition_doc
)
from utils import get_current_utc
from datetime import datetime
from app.config.config import Config

entity_bp = Blueprint('entity', __name__)

def validate_entity_name(name):
    """Validate entity name format."""
    if not name or not isinstance(name, str):
        return False
    if len(name.strip()) == 0 or len(name) > 100:
        return False
    return True

def validate_company_access(company_id):
    """Validate if company exists."""
    try:
        company_id = ObjectId(company_id) if isinstance(company_id, str) else company_id
        company = company_collection.find_one({'_id': company_id})
        return company is not None
    except Exception as e:
        print(f"Error validating company access: {str(e)}")
        return False

def validate_entity_against_definition(entity_data, definition):
    """Validate entity data against its definition."""
    entity_type = entity_data['type']
    
    # Check if entity type is allowed
    if entity_type not in definition['structure']['entityTypes']:
        return False, f"Entity type '{entity_type}' not allowed in definition"
    
    # Check required attributes
    required_attrs = definition['structure'].get('entityTypes', {}).get(entity_type, {}).get('requiredAttributes', [])
    for attr in required_attrs:
        if attr not in entity_data.get('attributes', {}):
            return False, f"Required attribute '{attr}' missing for type '{entity_type}'"
    
    # Validate attribute values against allowed values
    allowed_values = definition['structure'].get('entityTypes', {}).get(entity_type, {}).get('allowedValues', {})
    for attr, value in entity_data.get('attributes', {}).items():
        if attr in allowed_values and value not in allowed_values[attr]:
            return False, f"Invalid value for attribute '{attr}': must be one of {allowed_values[attr]}"
    
    # Validate parent-child relationship if parent exists
    if entity_data.get('parentId'):
        parent = entity_collection.find_one({'_id': ObjectId(entity_data['parentId'])})
        if not parent:
            return False, "Parent entity not found"
        
        # Check if this parent-child relationship is allowed
        valid_relationship = False
        for rel in definition['relationships']:
            if rel['parentType'] == parent['type'] and rel['childType'] == entity_type:
                valid_relationship = True
                # Check cardinality constraints
                if rel.get('constraints', {}).get('maxChildren'):
                    child_count = entity_collection.count_documents({
                        'parentId': parent['_id'],
                        'type': entity_type
                    })
                    if child_count >= rel['constraints']['maxChildren']:
                        return False, f"Maximum number of {entity_type} children reached for this {parent['type']}"
                break
        
        if not valid_relationship:
            return False, f"Invalid parent-child relationship: {parent['type']} -> {entity_type}"
    
    return True, None

@entity_bp.route('/entity-definitions', methods=['POST'])
def create_entity_definition():
    """Create a new entity definition for a company."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required fields
        required_fields = ['name', 'companyId', 'structure', 'relationships']
        if not all(field in data for field in required_fields):
            return jsonify({'error': f'Missing required fields: {required_fields}'}), 400

        # Validate company access
        if not validate_company_access(data['companyId']):
            return jsonify({'error': 'Invalid company ID'}), 404

        # Build and insert definition document
        definition_doc = build_entity_definition_doc(data)
        result = entity_definition_collection.insert_one(definition_doc)

        return jsonify({
            'id': str(result.inserted_id),
            'message': 'Entity definition created successfully'
        }), 201

    except Exception as e:
        return jsonify({'error': f'Failed to create entity definition: {str(e)}'}), 500

@entity_bp.route('/entity-definitions/<definition_id>', methods=['GET'])
def get_entity_definition(definition_id):
    """Get a specific entity definition."""
    try:
        definition = entity_definition_collection.find_one({'_id': ObjectId(definition_id)})
        if not definition:
            return jsonify({'error': 'Entity definition not found'}), 404

        # Convert ObjectIds to strings
        definition['_id'] = str(definition['_id'])
        definition['companyId'] = str(definition['companyId'])
        if definition.get('templateRef'):
            definition['templateRef'] = str(definition['templateRef'])

        return jsonify(definition)

    except Exception as e:
        return jsonify({'error': f'Failed to get entity definition: {str(e)}'}), 500

@entity_bp.route('/entity-definitions', methods=['GET'])
def get_entity_definitions():
    """Get all entity definitions for a company."""
    try:
        company_id = request.args.get('companyId')
        if not company_id:
            return jsonify({'error': 'companyId is required'}), 400

        # Validate company access
        if not validate_company_access(company_id):
            return jsonify({'error': 'Invalid company ID'}), 404

        # Get all active definitions for the company
        definitions = list(entity_definition_collection.find({
            'companyId': ObjectId(company_id),
            'status': 'active'
        }))

        # Convert ObjectIds to strings
        for definition in definitions:
            definition['_id'] = str(definition['_id'])
            definition['companyId'] = str(definition['companyId'])
            if definition.get('templateRef'):
                definition['templateRef'] = str(definition['templateRef'])

        return jsonify(definitions)

    except Exception as e:
        return jsonify({'error': f'Failed to get entity definitions: {str(e)}'}), 500

@entity_bp.route('/entity-definitions/<definition_id>', methods=['PUT'])
def update_entity_definition(definition_id):
    """Update an entity definition."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Get existing definition
        existing = entity_definition_collection.find_one({'_id': ObjectId(definition_id)})
        if not existing:
            return jsonify({'error': 'Entity definition not found'}), 404

        # Update the definition
        data['updatedAt'] = get_current_utc()
        result = entity_definition_collection.update_one(
            {'_id': ObjectId(definition_id)},
            {'$set': data}
        )

        return jsonify({
            'message': 'Entity definition updated successfully',
            'modified': result.modified_count > 0
        })

    except Exception as e:
        return jsonify({'error': f'Failed to update entity definition: {str(e)}'}), 500

@entity_bp.route('/entities', methods=['POST'])
def create_entity():
    """Create a new entity with validation against its definition."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required fields
        required_fields = ['name', 'type', 'companyId', 'definitionId']
        if not all(field in data for field in required_fields):
            return jsonify({'error': f'Missing required fields: {required_fields}'}), 400

        # Validate name format
        if not validate_entity_name(data['name']):
            return jsonify({'error': 'Invalid entity name. Must be non-empty string with max length 100'}), 400

        # Validate company access
        if not validate_company_access(data['companyId']):
            return jsonify({'error': 'Invalid company ID'}), 404

        # Get and validate against entity definition
        definition = entity_definition_collection.find_one({
            '_id': ObjectId(data['definitionId']),
            'status': 'active'
        })
        if not definition:
            return jsonify({'error': 'Entity definition not found or inactive'}), 404

        # Validate entity against definition
        is_valid, error_message = validate_entity_against_definition(data, definition)
        if not is_valid:
            return jsonify({'error': f'Entity validation failed: {error_message}'}), 400

        # If parentId is provided, validate and get path
        if data.get('parentId'):
            try:
                parent = entity_collection.find_one({'_id': ObjectId(data['parentId'])})
                if not parent:
                    return jsonify({'error': 'Parent entity not found'}), 404
                if str(parent['companyId']) != data['companyId']:
                    return jsonify({'error': 'Parent entity must belong to the same company'}), 400
                data['path'] = parent['path'] + [parent['_id']]
            except Exception as e:
                return jsonify({'error': f'Invalid parentId: {str(e)}'}), 400
        else:
            data['path'] = []

        # Create the entity
        entity_doc = build_entity_doc(data)
        result = entity_collection.insert_one(entity_doc)
        
        return jsonify({
            'id': str(result.inserted_id),
            'message': 'Entity created successfully'
        }), 201

    except Exception as e:
        return jsonify({'error': f'Failed to create entity: {str(e)}'}), 500

@entity_bp.route('/entities/<entity_id>', methods=['PUT'])
def update_entity(entity_id):
    """Update an entity with validation against its definition."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Get existing entity
        existing = entity_collection.find_one({'_id': ObjectId(entity_id)})
        if not existing:
            return jsonify({'error': 'Entity not found'}), 404

        # Get entity definition
        definition = entity_definition_collection.find_one({
            '_id': existing['definitionId'],
            'status': 'active'
        })
        if not definition:
            return jsonify({'error': 'Entity definition not found or inactive'}), 404

        # Merge existing data with updates for validation
        update_data = {**existing, **data}
        
        # Validate updated entity against definition
        is_valid, error_message = validate_entity_against_definition(update_data, definition)
        if not is_valid:
            return jsonify({'error': f'Entity validation failed: {error_message}'}), 400

        # Update the entity
        data['updatedAt'] = get_current_utc()
        result = entity_collection.update_one(
            {'_id': ObjectId(entity_id)},
            {'$set': data}
        )

        return jsonify({
            'message': 'Entity updated successfully',
            'modified': result.modified_count > 0
        })

    except Exception as e:
        return jsonify({'error': f'Failed to update entity: {str(e)}'}), 500

@entity_bp.route('/entities/templates', methods=['GET'])
def get_entity_templates():
    """Get all available entity templates."""
    try:
        # Get active templates
        templates = list(entity_template_collection.find({'status': 'active'}))
        
        # Convert ObjectIds to strings
        for template in templates:
            template['_id'] = str(template['_id'])
        
        return jsonify(templates)
    except Exception as e:
        return jsonify({'error': f'Failed to get templates: {str(e)}'}), 500

@entity_bp.route('/entities', methods=['GET'])
def get_entities():
    """Get all entities for a company."""
    try:
        company_id = request.args.get('companyId')
        if not company_id:
            return jsonify({'error': 'companyId is required'}), 400

        # Validate company exists
        try:
            company_id = ObjectId(company_id)
            company = company_collection.find_one({'_id': company_id})
            if not company:
                return jsonify({'error': 'Company not found'}), 404
        except Exception as e:
            return jsonify({'error': f'Invalid company ID format: {str(e)}'}), 400

        # Get all entities for the company
        entities = list(entity_collection.find({'companyId': company_id}))
        return json_response(entities)

    except Exception as e:
        print(f"Error in get_entities: {str(e)}")
        return jsonify({'error': f'Failed to get entities: {str(e)}'}), 500

@entity_bp.route('/entities/<entity_id>/employees', methods=['POST'])
def link_employee_to_entity(entity_id):
    """Link an existing employee to an entity."""
    try:
        data = request.json
        if not data or 'employeeId' not in data:
            return jsonify({'error': 'Employee ID is required'}), 400

        # Validate entity exists
        entity = entity_collection.find_one({'_id': ObjectId(entity_id)})
        if not entity:
            return jsonify({'error': 'Entity not found'}), 404

        # Validate employee exists and belongs to the same company
        employee = employee_collection.find_one({
            'employeeId': data['employeeId'],
            'companyId': entity['companyId']
        })
        if not employee:
            return jsonify({'error': 'Employee not found or does not belong to the same company'}), 404

        # Create asset document for employee
        asset_doc = {
            'name': employee['employeeName'],
            'type': 'employee',
            'entityId': ObjectId(entity_id),
            'companyId': entity['companyId'],
            'metadata': {
                'employeeId': employee['employeeId'],
                'employeeRef': str(employee['_id']),
                'designation': employee.get('employeeDesignation', ''),
                'email': employee.get('employeeEmail', ''),
                'mobile': employee.get('employeeMobile', '')
            }
        }

        # Check if employee is already linked to another entity
        existing_asset = asset_collection.find_one({
            'type': 'employee',
            'metadata.employeeId': employee['employeeId'],
            'companyId': entity['companyId']
        })

        if existing_asset:
            # Update existing asset with new entity
            result = asset_collection.update_one(
                {'_id': existing_asset['_id']},
                {
                    '$set': {
                        'entityId': ObjectId(entity_id),
                        'updatedAt': get_current_utc()
                    }
                }
            )
            message = 'Employee reassigned to new entity'
        else:
            # Create new asset
            result = asset_collection.insert_one(build_asset_doc(asset_doc, 'employee'))
            message = 'Employee linked to entity'

        return jsonify({
            'message': message,
            'entityId': str(entity_id),
            'employeeId': data['employeeId']
        })

    except Exception as e:
        return jsonify({'error': f'Failed to link employee: {str(e)}'}), 500

@entity_bp.route('/entities/<entity_id>', methods=['GET'])
def get_entity(entity_id):
    try:
        entity = entity_collection.find_one({'_id': ObjectId(entity_id)})
        if not entity:
            return jsonify({'error': 'Entity not found'}), 404
        
        return json_response(entity)
    except Exception as e:
        return jsonify({'error': f'Failed to get entity: {str(e)}'}), 500

@entity_bp.route('/entities/<entity_id>/children', methods=['GET'])
def get_children(entity_id):
    entity_type = request.args.get('type')
    query = {'parentId': ObjectId(entity_id)}
    
    if entity_type:
        query['type'] = entity_type
    
    children = list(entity_collection.find(query))
    return json_response(children)

@entity_bp.route('/entities/<entity_id>/descendants', methods=['GET'])
def get_descendants(entity_id):
    descendants = list(entity_collection.find({'path': ObjectId(entity_id)}))
    return json_response(descendants)

@entity_bp.route('/entities/<entity_id>/ancestors', methods=['GET'])
def get_ancestors(entity_id):
    entity = entity_collection.find_one({'_id': ObjectId(entity_id)})
    if not entity:
        return jsonify({'error': 'Entity not found'}), 404
    
    ancestors = list(entity_collection.find({'_id': {'$in': entity['path']}}))
    return json_response(ancestors)

@entity_bp.route('/entities/<entity_id>', methods=['DELETE'])
def delete_entity(entity_id):
    # Delete the entity and all its descendants
    entity_collection.delete_many({
        '$or': [
            {'_id': ObjectId(entity_id)},
            {'path': ObjectId(entity_id)}
        ]
    })
    
    # Delete all assets linked to this entity
    asset_collection.delete_many({'entityId': ObjectId(entity_id)})
    
    return jsonify({'success': True})

@entity_bp.route('/assets', methods=['POST'])
def create_asset():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required fields
        required_fields = ['name', 'entityId']
        if not all(field in data for field in required_fields):
            return jsonify({'error': f'Missing required fields: {required_fields}'}), 400

        # Validate entity exists
        try:
            entity = entity_collection.find_one({'_id': ObjectId(data['entityId'])})
            if not entity:
                return jsonify({'error': 'Entity not found'}), 404

            # Validate company access if entity is company-scoped
            if entity.get('companyId'):
                if not validate_company_access(str(entity['companyId'])):
                    return jsonify({'error': 'Invalid company access'}), 403
        except Exception as e:
            return jsonify({'error': f'Invalid entityId: {str(e)}'}), 400

        # Set orgId from entity
        data['orgId'] = str(entity['orgId'])
        
        # If it's an employee asset, validate against employee collection
        if data.get('type') == 'employee':
            employee = employee_collection.find_one({
                'employeeId': data.get('employeeId'),
                'companyId': entity.get('companyId')
            })
            if not employee:
                return jsonify({'error': 'Employee not found'}), 404
            data['metadata']['employeeRef'] = str(employee['_id'])

        asset_doc = build_asset_doc(data, data.get('type', 'generic'))
        result = asset_collection.insert_one(asset_doc)
        
        return jsonify({
            'id': str(result.inserted_id),
            'message': 'Asset created successfully'
        }), 201

    except Exception as e:
        return jsonify({'error': f'Failed to create asset: {str(e)}'}), 500

@entity_bp.route('/entities/<entity_id>/assets', methods=['GET'])
def get_entity_assets(entity_id):
    try:
        # Validate entity exists
        entity = entity_collection.find_one({'_id': ObjectId(entity_id)})
        if not entity:
            return jsonify({'error': 'Entity not found'}), 404

        asset_type = request.args.get('type')
        include_employee_details = request.args.get('include_employee_details', 'false').lower() == 'true'
        
        # Get all descendant entity IDs including the current entity
        entities = list(entity_collection.find({
            '$or': [
                {'_id': ObjectId(entity_id)},
                {'path': ObjectId(entity_id)}
            ]
        }))
        entity_ids = [entity['_id'] for entity in entities]
        
        # Query assets
        query = {'entityId': {'$in': entity_ids}}
        if asset_type:
            query['type'] = asset_type
        
        assets = list(asset_collection.find(query))
        
        # Process assets
        for asset in assets:
            asset['_id'] = str(asset['_id'])
            asset['entityId'] = str(asset['entityId'])
            asset['orgId'] = str(asset['orgId'])
            
            # Include employee details if requested and asset is employee type
            if include_employee_details and asset.get('type') == 'employee':
                employee_ref = asset.get('metadata', {}).get('employeeRef')
                if employee_ref:
                    employee = employee_collection.find_one({'_id': ObjectId(employee_ref)})
                    if employee:
                        employee['_id'] = str(employee['_id'])
                        employee['companyId'] = str(employee['companyId'])
                        asset['employeeDetails'] = employee
        
        return jsonify(assets)

    except Exception as e:
        return jsonify({'error': f'Failed to get assets: {str(e)}'}), 500

# Add new endpoint to move entities
@entity_bp.route('/entities/<entity_id>/move', methods=['POST'])
def move_entity(entity_id):
    try:
        data = request.json
        if not data or 'newParentId' not in data:
            return jsonify({'error': 'New parent ID is required'}), 400

        # Validate entity and new parent
        entity = entity_collection.find_one({'_id': ObjectId(entity_id)})
        new_parent = entity_collection.find_one({'_id': ObjectId(data['newParentId'])})

        if not entity:
            return jsonify({'error': 'Entity not found'}), 404
        if not new_parent:
            return jsonify({'error': 'New parent entity not found'}), 404

        # Prevent moving to a descendant
        if ObjectId(entity_id) in new_parent['path']:
            return jsonify({'error': 'Cannot move entity to its own descendant'}), 400

        # Update path for the entity and all its descendants
        old_path = entity['path']
        new_path = new_parent['path'] + [new_parent['_id']]

        # Update the entity
        entity_collection.update_one(
            {'_id': ObjectId(entity_id)},
            {
                '$set': {
                    'parentId': new_parent['_id'],
                    'path': new_path,
                    'updatedAt': get_current_utc()
                }
            }
        )

        # Update all descendants
        descendants = list(entity_collection.find({'path': ObjectId(entity_id)}))
        for desc in descendants:
            new_desc_path = new_path + desc['path'][len(old_path):]
            entity_collection.update_one(
                {'_id': desc['_id']},
                {
                    '$set': {
                        'path': new_desc_path,
                        'updatedAt': get_current_utc()
                    }
                }
            )

        return jsonify({'message': 'Entity moved successfully'})

    except Exception as e:
        return jsonify({'error': f'Failed to move entity: {str(e)}'}), 500

@entity_bp.route('/entity-definitions/from-template', methods=['POST'])
def create_definition_from_template():
    """Create a new entity definition for a company based on a template."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required fields
        required_fields = ['templateId', 'companyId', 'name']
        if not all(field in data for field in required_fields):
            return jsonify({'error': f'Missing required fields: {required_fields}'}), 400

        # Validate company access
        if not validate_company_access(data['companyId']):
            return jsonify({'error': 'Invalid company ID'}), 404

        # Get template
        template = entity_template_collection.find_one({'_id': ObjectId(data['templateId'])})
        if not template:
            return jsonify({'error': 'Template not found'}), 404

        # Create definition document
        definition_doc = {
            'name': data['name'],
            'companyId': ObjectId(data['companyId']),
            'templateRef': template['_id'],
            'description': data.get('description', template.get('description', '')),
            'structure': data.get('structure', template['structure']),
            'relationships': data.get('relationships', template['relationships']),
            'status': 'active',
            'createdAt': get_current_utc(),
            'updatedAt': get_current_utc(),
            'version': template['version'],
            'customizations': data.get('customizations', {})
        }

        # Insert the definition
        result = entity_definition_collection.insert_one(definition_doc)

        return jsonify({
            'id': str(result.inserted_id),
            'message': 'Entity definition created from template successfully'
        }), 201

    except Exception as e:
        return jsonify({'error': f'Failed to create entity definition from template: {str(e)}'}), 500

def generate_cytoscape_elements(template):
    """Generate Cytoscape-compatible elements from the template structure."""
    elements = []
    
    # Add nodes for each entity type
    for entity_type, config in template['structure'].get('entityTypes', {}).items():
        elements.append({
            'data': {
                'id': entity_type,
                'label': entity_type,
                'type': 'entity_type',
                'description': config.get('description', ''),
                'attributes': config.get('requiredAttributes', []),
                'validations': config.get('validations', {})
            },
            'classes': ['entity-type']
        })
    
    # Add edges for relationships
    for rel in template.get('relationships', []):
        if 'parentType' in rel and 'childType' in rel:
            constraints = rel.get('constraints', {})
            min_children = constraints.get('minChildren', '0')
            max_children = constraints.get('maxChildren', '∞')
            
            elements.append({
                'data': {
                    'id': f"{rel['parentType']}-{rel['childType']}",
                    'source': rel['parentType'],
                    'target': rel['childType'],
                    'label': f"{min_children}..{max_children}",
                    'relationship': 'parent-child',
                    'constraints': constraints
                },
                'classes': ['relationship']
            })
    
    return elements

@entity_bp.route('/entity-templates/<template_id>', methods=['GET'])
def get_template(template_id):
    """Get a specific entity template with its Cytoscape elements."""
    template = entity_template_collection.find_one({'_id': ObjectId(template_id)})
    if not template:
        return jsonify({'error': 'Template not found'}), 404
    
    # Generate Cytoscape elements
    template['graphElements'] = generate_cytoscape_elements(template)
    return jsonify(template)

@entity_bp.route('/entity-templates', methods=['GET'])
def get_templates():
    """Get all available entity templates."""
    try:
        # Get active templates
        templates = list(entity_template_collection.find({'status': 'active'}))
        
        # Convert ObjectIds to strings and add Cytoscape elements
        for template in templates:
            template['_id'] = str(template['_id'])
            template['graphElements'] = generate_cytoscape_elements(template)
        
        return jsonify(templates)
    except Exception as e:
        return jsonify({'error': f'Failed to get templates: {str(e)}'}), 500

@entity_bp.route('/entities/templates/<template_id>/clone', methods=['POST'])
def clone_template(template_id):
    """Clone an existing template for customization."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required fields
        required_fields = ['name', 'companyId']
        if not all(field in data for field in required_fields):
            return jsonify({'error': f'Missing required fields: {required_fields}'}), 400

        # Get source template
        template = entity_template_collection.find_one({'_id': ObjectId(template_id)})
        if not template:
            return jsonify({'error': 'Template not found'}), 404

        # Create new template document
        new_template = {
            **template,
            '_id': ObjectId(),  # Generate new ID
            'name': data['name'],
            'companyId': ObjectId(data['companyId']),
            'clonedFrom': str(template['_id']),
            'createdAt': get_current_utc(),
            'updatedAt': get_current_utc(),
            'status': 'active'
        }

        # Remove original template's metadata
        if 'createdAt' in new_template:
            del new_template['createdAt']
        if 'updatedAt' in new_template:
            del new_template['updatedAt']

        # Insert new template
        result = entity_template_collection.insert_one(new_template)

        return jsonify({
            'id': str(result.inserted_id),
            'message': 'Template cloned successfully'
        }), 201

    except Exception as e:
        return jsonify({'error': f'Failed to clone template: {str(e)}'}), 500

def json_response(data):
    """Convert MongoDB documents with ObjectIds to JSON response."""
    return json.loads(json_util.dumps(data))

@entity_bp.route('/entities/<entity_id>/manager', methods=['PUT'])
def assign_manager(entity_id):
    """Assign a manager to an entity."""
    try:
        data = request.json
        if not data or 'employeeId' not in data:
            return jsonify({'error': 'employeeId is required'}), 400

        # Get entity and validate
        entity = entity_collection.find_one({'_id': ObjectId(entity_id)})
        if not entity:
            return jsonify({'error': 'Entity not found'}), 404

        # Get entity definition
        definition = entity_definition_collection.find_one({'_id': entity['definitionId']})
        if not definition:
            return jsonify({'error': 'Entity definition not found'}), 404

        # Get the designation for this entity type
        entity_type = entity['type']
        designation = definition['structure']['entityTypes'][entity_type]['designation']

        # Validate employee exists and belongs to company
        employee = employee_collection.find_one({
            'employeeId': data['employeeId'],
            'companyId': entity['companyId']
        })
        if not employee:
            return jsonify({'error': 'Employee not found or does not belong to this company'}), 404

        # Update employee's designation
        employee_collection.update_one(
            {'_id': employee['_id']},
            {
                '$set': {
                    'employeeDesignation': designation,
                    'updatedAt': get_current_utc()
                }
            }
        )

        # Update entity with new manager
        update_result = entity_collection.update_one(
            {'_id': ObjectId(entity_id)},
            {
                '$set': {
                    'manager': {
                        'employeeId': data['employeeId'],
                        'assignedAt': get_current_utc(),
                        'status': 'filled'
                    },
                    'updatedAt': get_current_utc()
                }
            }
        )

        if update_result.modified_count == 0:
            return jsonify({'error': 'Failed to update entity'}), 500

        return jsonify({
            'message': 'Manager assigned successfully',
            'entityId': str(entity_id),
            'designation': designation
        })

    except Exception as e:
        return jsonify({'error': f'Failed to assign manager: {str(e)}'}), 500

@entity_bp.route('/entities/<entity_id>/manager', methods=['DELETE'])
def remove_manager(entity_id):
    """Remove the manager from an entity."""
    try:
        # Get entity
        entity = entity_collection.find_one({'_id': ObjectId(entity_id)})
        if not entity:
            return jsonify({'error': 'Entity not found'}), 404

        # Update entity to remove manager
        update_result = entity_collection.update_one(
            {'_id': ObjectId(entity_id)},
            {
                '$set': {
                    'manager': {
                        'employeeId': None,
                        'assignedAt': None,
                        'status': 'vacant'
                    },
                    'updatedAt': get_current_utc()
                }
            }
        )

        if update_result.modified_count == 0:
            return jsonify({'error': 'Failed to remove manager'}), 500

        return jsonify({
            'message': 'Manager removed successfully',
            'entityId': str(entity_id)
        })

    except Exception as e:
        return jsonify({'error': f'Failed to remove manager: {str(e)}'}), 500

@entity_bp.route('/entities/<entity_id>/manager', methods=['GET'])
def get_entity_manager(entity_id):
    """Get manager information for an entity."""
    try:
        entity = entity_collection.find_one({'_id': ObjectId(entity_id)})
        if not entity:
            return jsonify({'error': 'Entity not found'}), 404

        # Get entity definition
        definition = entity_definition_collection.find_one({'_id': entity['definitionId']})
        if not definition:
            return jsonify({'error': 'Entity definition not found'}), 404

        # Get designation for this entity type
        entity_type = entity['type']
        designation = definition['structure']['entityTypes'][entity_type]['designation']

        # Get manager details if exists
        manager_info = entity.get('manager', {'status': 'vacant'})
        if manager_info.get('employeeId'):
            employee = employee_collection.find_one({'employeeId': manager_info['employeeId']})
            if employee:
                manager_info['employeeName'] = employee.get('employeeName')
                manager_info['employeeEmail'] = employee.get('employeeEmail')

        return jsonify({
            'entityId': str(entity_id),
            'entityType': entity_type,
            'designation': designation,
            'manager': manager_info
        })

    except Exception as e:
        return jsonify({'error': f'Failed to get manager information: {str(e)}'}), 500

# Add company validation middleware
def validate_company_context(f):
    """Middleware to validate company context and prevent cross-company data access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Get company ID from request
            company_id = request.args.get('companyId') or request.json.get('companyId')
            
            if not company_id:
                return jsonify({'error': 'Company ID is required'}), 400

            # If we have an entity_id in the URL, validate it belongs to the company
            entity_id = kwargs.get('entity_id')
            if entity_id:
                entity = entity_collection.find_one({'_id': ObjectId(entity_id)})
                if not entity:
                    return jsonify({'error': 'Entity not found'}), 404
                
                if str(entity['companyId']) != str(company_id):
                    return jsonify({'error': 'Access denied: Entity does not belong to the company'}), 403

            # If we have an employee_id in the URL, validate it belongs to the company
            employee_id = kwargs.get('employee_id')
            if employee_id:
                employee = employee_collection.find_one({
                    'employeeId': employee_id,
                    'companyId': ObjectId(company_id)
                })
                if not employee:
                    return jsonify({'error': 'Access denied: Employee not found in company'}), 403

            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': f'Company validation failed: {str(e)}'}), 500
    return decorated_function

# Update the employee endpoints with company validation

@entity_bp.route('/entities/<entity_id>/employees', methods=['GET'])
@validate_company_context
def get_entity_employees(entity_id):
    """Get all employees under an entity (including sub-entities)."""
    try:
        company_id = request.args.get('companyId')
        
        # Get the entity (company validation already done in middleware)
        entity = entity_collection.find_one({
            '_id': ObjectId(entity_id),
            'companyId': ObjectId(company_id)  # Extra company check
        })

        # Include sub-entities flag
        include_sub_entities = request.args.get('include_sub_entities', 'true').lower() == 'true'

        # Build query for finding all relevant entities within the company
        entity_query = {
            'companyId': ObjectId(company_id),  # Ensure company isolation
            '$or': [
                {'_id': ObjectId(entity_id)}
            ]
        }
        if include_sub_entities:
            entity_query['$or'].append({'path': ObjectId(entity_id)})

        # Get all relevant entities
        entities = list(entity_collection.find(entity_query))
        entity_ids = [e['_id'] for e in entities]

        # Get all assets (employees) linked to these entities
        employee_assets = list(asset_collection.find({
            'entityId': {'$in': entity_ids},
            'type': 'employee',
            'companyId': ObjectId(company_id)  # Ensure company isolation
        }))

        # Get all employee IDs
        employee_ids = [asset['metadata']['employeeId'] for asset in employee_assets]

        # Get detailed employee information
        employees = list(employee_collection.find({
            'employeeId': {'$in': employee_ids},
            'status': 'active'
        }))

        # Enhance employee data with entity information
        enhanced_employees = []
        for employee in employees:
            # Find the asset for this employee
            asset = next((a for a in employee_assets if a['metadata']['employeeId'] == employee['employeeId']), None)
            if asset:
                # Find the entity this employee belongs to
                emp_entity = next((e for e in entities if e['_id'] == asset['entityId']), None)
                if emp_entity:
                    enhanced_employees.append({
                        'employeeId': employee['employeeId'],
                        'employeeName': employee['employeeName'],
                        'employeeEmail': employee.get('employeeEmail'),
                        'employeeMobile': employee.get('employeeMobile'),
                        'employeeDesignation': employee.get('employeeDesignation'),
                        'entity': {
                            'id': str(emp_entity['_id']),
                            'name': emp_entity['name'],
                            'type': emp_entity['type']
                        }
                    })

        return jsonify({
            'entityId': str(entity_id),
            'entityName': entity['name'],
            'entityType': entity['type'],
            'totalEmployees': len(enhanced_employees),
            'employees': enhanced_employees
        })

    except Exception as e:
        return jsonify({'error': f'Failed to get employees: {str(e)}'}), 500

@entity_bp.route('/employees/<employee_id>/reportees', methods=['GET'])
@validate_company_context
def get_employee_reportees(employee_id):
    """Get all employees reporting to a specific employee."""
    try:
        company_id = request.args.get('companyId')
        
        # Get the employee (company validation already done in middleware)
        manager = employee_collection.find_one({
            'employeeId': employee_id,
            'companyId': ObjectId(company_id)  # Extra company check
        })

        # Get all employees reporting to this employee within the same company
        reportees = list(employee_collection.find({
            'employeeReportingId': employee_id,
            'companyId': ObjectId(company_id),  # Ensure company isolation
            'status': 'active'
        }))

        # Get entity information for each reportee
        enhanced_reportees = []
        for reportee in reportees:
            # Find the asset for this employee
            asset = asset_collection.find_one({
                'type': 'employee',
                'metadata.employeeId': reportee['employeeId']
            })
            if asset:
                # Get entity information
                entity = entity_collection.find_one({'_id': asset['entityId']})
                if entity:
                    enhanced_reportees.append({
                        'employeeId': reportee['employeeId'],
                        'employeeName': reportee['employeeName'],
                        'employeeEmail': reportee.get('employeeEmail'),
                        'employeeMobile': reportee.get('employeeMobile'),
                        'employeeDesignation': reportee.get('employeeDesignation'),
                        'entity': {
                            'id': str(entity['_id']),
                            'name': entity['name'],
                            'type': entity['type']
                        }
                    })

        return jsonify({
            'managerId': employee_id,
            'managerName': manager['employeeName'],
            'managerDesignation': manager.get('employeeDesignation'),
            'totalReportees': len(enhanced_reportees),
            'reportees': enhanced_reportees
        })

    except Exception as e:
        return jsonify({'error': f'Failed to get reportees: {str(e)}'}), 500

@entity_bp.route('/employees/search', methods=['GET'])
@validate_company_context
def search_employees():
    """Search employees with various filters."""
    try:
        company_id = request.args.get('companyId')
        
        # Build the query with company isolation
        query = {
            'companyId': ObjectId(company_id),
            'status': 'active'
        }

        # Add other search filters
        entity_type = request.args.get('entityType')
        designation = request.args.get('designation')
        reporting_to = request.args.get('reportingTo')
        search_term = request.args.get('search')
        
        if search_term:
            query['$or'] = [
                {'employeeName': {'$regex': search_term, '$options': 'i'}},
                {'employeeEmail': {'$regex': search_term, '$options': 'i'}},
                {'employeeId': {'$regex': search_term, '$options': 'i'}}
            ]
        
        if designation:
            query['employeeDesignation'] = designation
        
        if reporting_to:
            # Verify reporting manager belongs to same company
            manager = employee_collection.find_one({
                'employeeId': reporting_to,
                'companyId': ObjectId(company_id)
            })
            if not manager:
                return jsonify({'error': 'Invalid reporting manager'}), 400
            query['employeeReportingId'] = reporting_to

        # Get employees matching the query
        employees = list(employee_collection.find(query))

        # If entity type filter is present, filter by entity type
        if entity_type:
            # Get all entities of the specified type within the company
            entities = list(entity_collection.find({
                'type': entity_type,
                'companyId': ObjectId(company_id)  # Ensure company isolation
            }))
            entity_ids = [e['_id'] for e in entities]

            # Get assets for these entities
            assets = list(asset_collection.find({
                'entityId': {'$in': entity_ids},
                'type': 'employee',
                'companyId': ObjectId(company_id)  # Ensure company isolation
            }))

            # Filter employees based on assets
            asset_employee_ids = [a['metadata']['employeeId'] for a in assets]
            employees = [e for e in employees if e['employeeId'] in asset_employee_ids]

        # Enhance employee data with entity information
        enhanced_employees = []
        for employee in employees:
            # Get asset information
            asset = asset_collection.find_one({
                'type': 'employee',
                'metadata.employeeId': employee['employeeId']
            })
            if asset:
                # Get entity information
                entity = entity_collection.find_one({'_id': asset['entityId']})
                if entity:
                    enhanced_employees.append({
                        'employeeId': employee['employeeId'],
                        'employeeName': employee['employeeName'],
                        'employeeEmail': employee.get('employeeEmail'),
                        'employeeMobile': employee.get('employeeMobile'),
                        'employeeDesignation': employee.get('employeeDesignation'),
                        'reportingTo': employee.get('employeeReportingId'),
                        'entity': {
                            'id': str(entity['_id']),
                            'name': entity['name'],
                            'type': entity['type']
                        }
                    })

        return jsonify({
            'totalEmployees': len(enhanced_employees),
            'employees': enhanced_employees
        })

    except Exception as e:
        return jsonify({'error': f'Failed to search employees: {str(e)}'}), 500

@entity_bp.route('/employees/reporting-tree/<employee_id>', methods=['GET'])
@validate_company_context
def get_reporting_tree(employee_id):
    """Get the complete reporting tree for an employee (both up and down)."""
    try:
        company_id = request.args.get('companyId')
        
        # Get the employee (company validation already done in middleware)
        employee = employee_collection.find_one({
            'employeeId': employee_id,
            'companyId': ObjectId(company_id)  # Extra company check
        })

        def get_manager_chain(emp):
            """Get the chain of managers above this employee."""
            chain = []
            current = emp
            while current.get('employeeReportingId'):
                manager = employee_collection.find_one({
                    'employeeId': current['employeeReportingId'],
                    'companyId': ObjectId(company_id)  # Ensure company isolation
                })
                if not manager or manager['employeeId'] in [e['employeeId'] for e in chain]:
                    break
                chain.append({
                    'employeeId': manager['employeeId'],
                    'employeeName': manager['employeeName'],
                    'designation': manager.get('employeeDesignation')
                })
                current = manager
            return chain

        def get_reportees_tree(emp):
            """Get the tree of reportees under this employee."""
            reportees = list(employee_collection.find({
                'employeeReportingId': emp['employeeId'],
                'companyId': ObjectId(company_id),  # Ensure company isolation
                'status': 'active'
            }))
            
            tree = []
            for reportee in reportees:
                reportee_data = {
                    'employeeId': reportee['employeeId'],
                    'employeeName': reportee['employeeName'],
                    'designation': reportee.get('employeeDesignation'),
                    'reportees': get_reportees_tree(reportee)
                }
                tree.append(reportee_data)
            return tree

        # Build the complete tree
        reporting_tree = {
            'employee': {
                'employeeId': employee['employeeId'],
                'employeeName': employee['employeeName'],
                'designation': employee.get('employeeDesignation')
            },
            'managementChain': get_manager_chain(employee),
            'reportees': get_reportees_tree(employee)
        }

        return jsonify(reporting_tree)

    except Exception as e:
        return jsonify({'error': f'Failed to get reporting tree: {str(e)}'}), 500 