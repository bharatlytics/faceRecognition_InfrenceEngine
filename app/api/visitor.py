from flask import Blueprint, request, jsonify, send_file, Response, g, abort
from db import visitor_collection, visitor_image_fs, visitor_embedding_fs, visit_collection, embedding_jobs_collection, employee_collection, employee_image_fs, employee_embedding_fs
from models import build_visitor_doc, build_visit_doc
from utils import (
    validate_required_fields, error_response, validate_email_format,
    validate_phone_format, is_unique_email, is_unique_phone,
    parse_datetime, format_datetime, get_current_utc
)
from app.config.config import Config
from datetime import datetime, timedelta, timezone
import qrcode
from qrcode.image.pil import PilImage
import io
import base64
from bson import ObjectId
import functools
import re
import pickle
from embeddings import fetch_embedding_from_doc, store_embedding
from gridfs import GridFS
from bson.errors import InvalidId
from PIL import Image, ImageDraw, ImageFont

visitor_bp = Blueprint('visitor', __name__)

# --- Authentication Decorator ---
def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not request.headers.get('X-Auth-Token'):
            abort(401, description='Unauthorized')
        return f(*args, **kwargs)
    return wrapper

@visitor_bp.route('/register', methods=['POST'])
def register_visitor():
    try:
        required_fields = ['companyId', 'visitorName', 'phone', 'hostEmployeeId']
        valid, msg = validate_required_fields(request.form, required_fields)
        if not valid:
            return error_response(msg, 400)

        data = {field: request.form[field] for field in required_fields}
        optional_fields = [
            'visitorType', 'idType', 'idNumber', 'email',
            'organization', 'purpose', 'status', 'blacklisted'
        ]
        data.update({k: request.form[k] for k in optional_fields if k in request.form})
        # Validate visitor-specific fields
        validation_errors = validate_visitor_data(data)
        if validation_errors:
            return error_response('\n'.join(validation_errors), 400)
        # Verify host employee exists and is active
        host_employee = None
        try:
            host_employee = employee_collection.find_one({
                '_id': ObjectId(data['hostEmployeeId']),
                'companyId': ObjectId(data['companyId']),
                'status': 'active',
                'blacklisted': False
            })
        except (InvalidId, TypeError):
            host_employee = employee_collection.find_one({
                'employeeId': data['hostEmployeeId'],
                'companyId': ObjectId(data['companyId']),
                'status': 'active',
                'blacklisted': False
            })
        if not host_employee:
            return error_response('Host employee not found or not active.', 400)
        # Email/phone validation
        if data.get('email'):
            if not validate_email_format(data['email']):
                return error_response('Invalid email format.', 400)
        if not validate_phone_format(data['phone']):
            return error_response('Invalid phone number format.', 400)
        # Process visitor face images (store directly, no Pillow)
        required_face_positions = ['left', 'right', 'center']
        image_dict = {}
        document_dict = {}
        for position in required_face_positions:
            if position not in request.files:
                return error_response(f'Visitor face image for {position} position is required.', 400)
            face_image = request.files[position]
            # Store the uploaded file directly in GridFS
            face_image_id = visitor_image_fs.put(
                face_image.stream,
                filename=f"{data['companyId']}_{position}_face.jpg",
                metadata={
                    'companyId': data['companyId'],
                    'type': f'face_image_{position}',
                    'timestamp': get_current_utc()
                }
            )
            image_dict[position] = face_image_id
        # Process ID documents if provided (store directly, no Pillow)
        id_documents = ['pan_card', 'aadhar_card', 'driving_license', 'passport']
        for doc_type in id_documents:
            if doc_type in request.files:
                doc_file = request.files[doc_type]
                doc_id = visitor_image_fs.put(
                    doc_file.stream,
                    filename=f"{data['companyId']}_{doc_type}.jpg",
                    metadata={
                        'companyId': data['companyId'],
                        'type': f'{doc_type}_image',
                        'timestamp': get_current_utc()
                    }
                )
                document_dict[doc_type] = doc_id
        # Build and insert visitor document
        visitor_doc = build_visitor_doc(
            data,
            image_dict,
            {},
            document_dict
        )
        result = visitor_collection.insert_one(visitor_doc)
        visitor_id = result.inserted_id
        if not visitor_id:
            return error_response('Failed to register visitor.', 500)
        # Enqueue embedding jobs (worker will handle embedding/duplicate logic)
        embeddings_dict = {}
        for model in Config.ALLOWED_MODELS:
            job = {
                "employeeId": ObjectId(host_employee['_id']),
                "companyId": ObjectId(data['companyId']),
                "visitorId": visitor_id,
                "model": model,
                "status": "queued",
                "createdAt": get_current_utc(),
                "params": {}
            }
            embedding_jobs_collection.insert_one(job)
            embeddings_dict[model] = {'status': 'queued', 'queuedAt': get_current_utc()}
        # Handle embedding file upload if present
        embedding_attached = request.form.get('embeddingAttached', 'false').lower() == 'true'
        embedding_version = request.form.get('embeddingVersion')
        if embedding_attached:
            if not embedding_version or 'embedding' not in request.files:
                return error_response('embeddingVersion and embedding file required when embeddingAttached is true')
            if embedding_version not in Config.ALLOWED_MODELS:
                return error_response('Embedding model not allowed.', 400)
            embedding_file = request.files['embedding']
            try:
                file_content = embedding_file.read()
                embedding_filename = embedding_file.filename
                embedding_metadata = {
                    'companyId': data['companyId'],
                    'visitorId': str(visitor_id),
                    'model': embedding_version,
                    'type': 'embedding',
                    'timestamp': get_current_utc()
                }
                emb_entry = store_embedding(file_content, embedding_filename, embedding_metadata, embedding_version)
                emb_entry['status'] = 'done'
                emb_entry['finishedAt'] = get_current_utc()
                embeddings_dict[embedding_version] = emb_entry
                # Update the visitor document with the new embedding entry
                visitor_collection.update_one(
                    {'_id': visitor_id},
                    {'$set': {f'visitorEmbeddings.{embedding_version}': emb_entry}}
                )
            except Exception as e:
                visitor_collection.update_one(
                    {'_id': visitor_id},
                    {'$set': {'status': 'incomplete', 'lastUpdated': get_current_utc()}}
                )
                return error_response(f'Error storing embedding: {e}', 400)
        # Update visitor document with embeddings_dict (for queued jobs and/or attached embedding)
        visitor_collection.update_one({'_id': visitor_id}, {'$set': {'visitorEmbeddings': embeddings_dict}})
        return jsonify({
            'message': 'Visitor registration successful',
            '_id': str(visitor_id),
            'embeddingStatus': {k: v.get('status', 'unknown') for k, v in embeddings_dict.items()}
        }), 201
    except Exception as e:
        print(f"Error in register_visitor: {e}")
        return error_response(str(e), 500)

def has_overlapping_visit(visitor_id, new_start, new_end):
    overlap = visit_collection.find_one({
        "visitorId": ObjectId(visitor_id),
        "status": {"$in": ["scheduled", "checked_in"]},
        "$or": [
            {"expectedArrival": {"$lt": new_end}, "expectedDeparture": {"$gt": new_start}}
        ]
    })
    return overlap is not None

def generate_visitor_pass(visitor, host, data, visit_id, arrival, new_end):
    import qrcode
    from PIL import Image, ImageDraw, ImageFont
    import io
    from datetime import datetime
    from bson import ObjectId

    def format_datetime(dt):
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except ValueError:
                return dt
        return dt.strftime("%d %b %Y, %H:%M")

    # Color scheme - enhanced professional palette
    COLORS = {
        'primary': (0, 51, 102),        # Deep blue for header and titles
        'secondary': (240, 240, 240),   # Light grey for backgrounds
        'accent': (0, 102, 204),        # Brighter blue for accents
        'text': (33, 33, 33),           # Near black for text
        'subtext': (100, 100, 100),     # Grey for secondary text
        'white': (255, 255, 255),       # White
        'border': (220, 220, 220),      # Lighter border
        'section_bg': (248, 250, 255)   # Very light blue for section backgrounds
    }

    # Dimensions - optimized proportions
    DIMENSIONS = {
        'width': 1000,
        'height': 1400,
        'margin': 50,
        'col_gap': 40,
        'qr_size': 300,
        'img_size': 300
    }

    # Spacing - improved consistency
    SPACING = {
        'section': 25,
        'row': 30,
        'heading': 20
    }

    # Generate QR code with improved error correction
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2
    )
    qr.add_data(str(visit_id))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")

    # Create canvas with consistent dimensions
    pass_img = Image.new('RGB', (DIMENSIONS['width'], DIMENSIONS['height']), COLORS['white'])
    draw = ImageDraw.Draw(pass_img)

    # Improved font fallback system
    try:
        title_font = ImageFont.truetype("Arial.ttf", 42)
        header_font = ImageFont.truetype("Arial.ttf", 28)
        label_font = ImageFont.truetype("Arial-Bold.ttf", 20)
        text_font = ImageFont.truetype("Arial.ttf", 20)
        small_font = ImageFont.truetype("Arial.ttf", 18)
    except:
        try:
            title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 42)
            header_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
            label_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
            text_font = ImageFont.truetype("DejaVuSans.ttf", 20)
            small_font = ImageFont.truetype("DejaVuSans.ttf", 18)
        except:
            title_font = ImageFont.load_default()
            header_font = ImageFont.load_default()
            label_font = ImageFont.load_default()
            text_font = ImageFont.load_default()
            small_font = ImageFont.load_default()

    margin = DIMENSIONS['margin']
    col_gap = DIMENSIONS['col_gap']
    col_width = (DIMENSIONS['width'] - 2 * margin - col_gap) // 2
    y = 0

    # Enhanced header
    header_height = 110
    # Main header rectangle
    draw.rectangle([(0, 0), (DIMENSIONS['width'], header_height)], fill=COLORS['primary'])
    
    # Add a subtle accent line at the bottom of header
    accent_height = 3
    draw.rectangle([(0, header_height-accent_height), (DIMENSIONS['width'], header_height)], fill=COLORS['accent'])
    
    # Position title text with more padding
    draw.text((margin, (header_height - 42) // 2), "VISITOR PASS", fill=COLORS['white'], font=title_font)
    
    # Better positioned ID text
    visit_id_text = f"ID: {visit_id}"
    visit_id_width = draw.textlength(visit_id_text, font=small_font)
    draw.text((DIMENSIONS['width'] - margin - visit_id_width, (header_height - 18) // 2), 
              visit_id_text, fill=COLORS['white'], font=small_font)
    
    y = header_height + margin

    # --- Left Column: All Text Info ---
    left_x = margin
    left_y = y
    
    def draw_section(draw, x, y, width, title, data_rows):
        # Calculate section height accounting for multiline values
        section_height = SPACING['heading'] + header_font.size + 15
        for label, value in data_rows:
            lines = str(value) if value is not None else ''
            lines = str(lines).split('\n')
            section_height += max(1, len(lines)) * SPACING['row']
        section_height += SPACING['section'] // 2  # Reduce bottom padding
        
        # Draw section box with consistent rounded corners effect
        corner_radius = 5  # Subtle rounded corner effect
        draw.rectangle(
            [(x - 10, y - 10), (x + width + 10, y + section_height)],
            fill=COLORS['section_bg'], 
            outline=COLORS['border'], 
            width=1
        )
        
        # Draw section title
        draw.text((x, y), title, fill=COLORS['primary'], font=header_font)
        y += SPACING['heading'] + header_font.size
        
        # Draw separator line
        draw.line([(x, y), (x + width, y)], fill=COLORS['border'], width=1)
        y += 15
        
        # Fixed label width for alignment
        label_width = 150
        value_x = x + label_width
        
        # Draw each label-value pair
        for label, value in data_rows:
            draw.text((x, y), label, fill=COLORS['primary'], font=label_font)
            
            # Handle multiline values
            lines = str(value) if value is not None else ''
            lines = str(lines).split('\n')
            for i, line in enumerate(lines):
                line_y = y + (i * SPACING['row'])
                draw.text((value_x, line_y), line, fill=COLORS['text'], font=text_font)
            
            y += max(1, len(lines)) * SPACING['row']
            
        return y + SPACING['section'] // 2, section_height

    # Visitor information section
    visitor_data = [
        ("Name:", visitor.get('visitorName', '')),
        ("Company:", visitor.get('organization', '')),
        ("Email:", visitor.get('email', '')),
        ("Phone:", visitor.get('phone', '')),
        ("ID Type:", visitor.get('idType', '')),
        ("ID Number:", visitor.get('idNumber', ''))
    ]
    left_y, v_section = draw_section(draw, left_x, left_y, col_width, "Visitor Information", visitor_data)
    
    # Host information section
    host_data = [
        ("Name:", host.get('employeeName', '')),
        ("Department:", host.get('department', '')),
        ("Designation:", host.get('employeeDesignation', '')),
        ("Email:", host.get('email', '')),
        ("Phone:", host.get('phone', ''))
    ]
    left_y, h_section = draw_section(draw, left_x, left_y, col_width, "Host Information", host_data)
    
    # Visit details section
    visit_data = [
        ("Purpose:", data.get('purpose', '')),
        ("Arrival:", format_datetime(arrival)),
        ("Departure:", format_datetime(new_end)),
        ("Location:", data.get('location', ''))
    ]
    left_y, vis_section = draw_section(draw, left_x, left_y, col_width, "Visit Details", visit_data)
    
    # Access information section
    access_zones = data.get('accessAreas', [])
    if not access_zones and data.get('accessZones'):
        access_zones = data.get('accessZones')
    if access_zones:
        areas_text = '\n'.join(f"• {area}" for area in access_zones)
        access_data = [("Access Zones:", areas_text)]
        left_y, acc_section = draw_section(draw, left_x, left_y, col_width, "Access Information", access_data)
    else:
        acc_section = 0

    # Calculate total left column height
    left_col_height = (v_section + h_section + vis_section + acc_section)

    # --- Right Column: Visitor Image (top), QR Code (bottom) ---
    right_x = margin + col_width + col_gap
    right_y = y
    right_col_height = left_col_height
    
    # Calculate space for image and QR
    img_space = DIMENSIONS['img_size']
    qr_space = DIMENSIONS['qr_size']
    vertical_gap = 40
    total_content_height = img_space + qr_space + vertical_gap
    
    # Center content vertically in right column
    start_y = right_y + max(0, (right_col_height - total_content_height) // 2)
    
    # Visitor image with improved styling
    visitor_img = None
    img_box = (
        right_x + (col_width - DIMENSIONS['img_size']) // 2, 
        start_y, 
        right_x + (col_width + DIMENSIONS['img_size']) // 2, 
        start_y + DIMENSIONS['img_size']
    )
    try:
        img_id = None
        # Try different possible image fields in priority order
        if visitor.get('visitorImages', {}).get('center'):
            img_id = visitor['visitorImages']['center']
        elif visitor.get('faceImages', {}).get('center'):
            img_id = visitor['faceImages']['center']
        elif visitor.get('faceImageCenter'):
            img_id = visitor['faceImageCenter']
        if img_id:
            if not isinstance(img_id, ObjectId):
                img_id = ObjectId(img_id)
            img_bytes = visitor_image_fs.get(img_id).read()
            visitor_img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
            visitor_img = visitor_img.resize((DIMENSIONS['img_size'], DIMENSIONS['img_size']))
    except Exception as e:
        visitor_img = None
    if visitor_img:
        # Create a circular mask
        mask = Image.new('L', (DIMENSIONS['img_size'], DIMENSIONS['img_size']), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, DIMENSIONS['img_size'], DIMENSIONS['img_size']), fill=255)
        # Draw border circle first
        border_size = 4
        border_box = (
            img_box[0] - border_size,
            img_box[1] - border_size,
            img_box[2] + border_size,
            img_box[3] + border_size
        )
        draw.ellipse(border_box, fill=COLORS['primary'])
        # Paste the visitor image with the mask (no offset)
        pass_img.paste(visitor_img, img_box[:2], mask)
    else:
        # Improved placeholder for missing image
        # Draw circle with border
        draw.ellipse(img_box, fill=COLORS['secondary'], outline=COLORS['primary'], width=2)
        # Add person icon or text placeholder
        no_img_text = "No Image"
        text_w = draw.textlength(no_img_text, font=text_font)
        draw.text(
            (img_box[0] + (DIMENSIONS['img_size'] - text_w) // 2, 
             img_box[1] + DIMENSIONS['img_size']//2 - 10), 
            no_img_text, fill=COLORS['subtext'], font=text_font
        )
    
    # QR code below image with improved styling
    qr_y = img_box[3] + vertical_gap
    qr_box_size = DIMENSIONS['qr_size']
    qr_box_x = right_x + (col_width - qr_box_size) // 2
    qr_box_y = qr_y
    
    # Enhanced QR code border
    qr_border = 16
    draw.rectangle(
        [
            (qr_box_x - qr_border, qr_box_y - qr_border),
            (qr_box_x + qr_box_size + qr_border, qr_box_y + qr_box_size + qr_border)
        ],
        fill=COLORS['white'], outline=COLORS['border'], width=2
    )
    
    # Add subtle drop shadow effect
    shadow_offset = 3
    shadow_color = (240, 240, 240)
    draw.rectangle(
        [
            (qr_box_x - qr_border + shadow_offset, qr_box_y - qr_border + shadow_offset),
            (qr_box_x + qr_box_size + qr_border + shadow_offset, qr_box_y + qr_box_size + qr_border + shadow_offset)
        ],
        fill=shadow_color, outline=shadow_color
    )
    
    # Paste QR code on top
    resized_qr = qr_img.resize((qr_box_size, qr_box_size))
    pass_img.paste(resized_qr, (qr_box_x, qr_box_y))

    # Set y for instructions below both columns with better spacing
    below_cols_y = y + max(left_col_height, right_col_height) + 40

    # --- Instructions (full width) ---
    instr_x = margin
    instr_y = below_cols_y
    instr_width = DIMENSIONS['width'] - 2 * margin
    instr_height = 140
    instr_pad_x = 30
    instr_pad_y = 24
    instr_border = 2
    
    # Better styled instructions box
    instr_box = [
        (instr_x - 10, instr_y - 10),
        (instr_x + instr_width + 10, instr_y + instr_height)
    ]
    
    # Draw instructions box with enhanced styling
    draw.rectangle(instr_box, fill=COLORS['section_bg'], outline=COLORS['border'], width=instr_border)
    draw.text((instr_x + instr_pad_x, instr_y + instr_pad_y - 8), "Instructions:", fill=COLORS['primary'], font=header_font)
    
    # Add separator line
    line_y = instr_y + instr_pad_y + header_font.size
    draw.line([(instr_x + instr_pad_x, line_y), (instr_x + instr_width - instr_pad_x, line_y)], fill=COLORS['border'], width=1)
    
    instr_y = line_y + 15
    
    # Improved instruction bullet points
    instructions = [
        "• Present this QR code at reception",
        "• Keep this pass visible at all times",
        "• Valid only during specified time period",
        "• Return to reception upon departure"
    ]
    
    for instruction in instructions:
        draw.text((instr_x + instr_pad_x, instr_y), instruction, fill=COLORS['text'], font=text_font)
        instr_y += SPACING['row']

    # --- Authorization/Signature Section ---
    signature_y = instr_box[1][1] + 30  # Add vertical margin below instructions
    signature_section_height = 150
    
    # Enhanced authorization box
    auth_box = [
        (margin - 10, signature_y - 10),
        (DIMENSIONS['width'] - margin + 10, signature_y + signature_section_height)
    ]
    
    draw.rectangle(auth_box, fill=COLORS['white'], outline=COLORS['border'], width=2)
    
    # Improved header for authorization section
    draw.text((margin + 20, signature_y + 10), "Authorization", fill=COLORS['primary'], font=header_font)
    
    # Add separator line
    auth_header_y = signature_y + 10 + header_font.size
    draw.line([(margin + 20, auth_header_y + 5), (DIMENSIONS['width'] - margin - 20, auth_header_y + 5)], 
              fill=COLORS['border'], width=1)
    
    # Equal width columns for signature fields
    total_width = DIMENSIONS['width'] - (2 * margin) - 40
    signature_width = total_width // 3
    
    field_y = signature_y + header_font.size + 40
    line_y = field_y + 40
    
    # Function for drawing signature fields with consistent styling
    def draw_signature_field(x, title, subtitle):
        draw.text((x, field_y), title, fill=COLORS['primary'], font=label_font)
        draw.line([(x, line_y), (x + signature_width - 20, line_y)], fill=COLORS['text'], width=1)
        draw.text((x, line_y + 10), subtitle, fill=COLORS['subtext'], font=small_font)
    
    # Evenly spaced signature fields
    sec_entry_x = margin + 20
    draw_signature_field(sec_entry_x, "Security (Entry)", "Name & Timestamp")
    
    host_x = sec_entry_x + signature_width
    draw_signature_field(host_x, "Host Approval", "Signature & Date")
    
    exit_x = host_x + signature_width
    draw_signature_field(exit_x, "Security (Exit)", "Name & Timestamp")

    # --- Footer ---
    footer_y = DIMENSIONS['height'] - 70
    
    # Enhanced footer with subtle gradient
    draw.rectangle([(0, footer_y), (DIMENSIONS['width'], DIMENSIONS['height'])], fill=COLORS['secondary'])
    
    # Add subtle accent line at top of footer
    accent_height = 2
    draw.rectangle([(0, footer_y), (DIMENSIONS['width'], footer_y + accent_height)], fill=COLORS['accent'])
    
    # Center footer text
    footer_text = "This pass must be worn visibly at all times while on the premises."
    footer_text_width = draw.textlength(footer_text, font=text_font)
    draw.text(
        ((DIMENSIONS['width'] - footer_text_width) // 2, footer_y + 25), 
        footer_text, fill=COLORS['primary'], font=text_font
    )

    # Return the image as bytes
    img_byte_arr = io.BytesIO()
    pass_img.save(img_byte_arr, format='PNG', quality=95)
    return img_byte_arr.getvalue()

@visitor_bp.route('/<visitorId>/schedule-visit', methods=['POST'])
def schedule_visit(visitorId):
    if not request.is_json:
        return error_response("Request must be application/json", 415)
    data = request.get_json()
    try:
        required_fields = ['companyId', 'hostEmployeeId', 'expectedArrival']
        valid, msg = validate_required_fields(data, required_fields)
        if not valid:
            return error_response(msg, 400)
            
        # Parse dates to UTC
        arrival = parse_datetime(data['expectedArrival'])
        new_end = parse_datetime(data.get('expectedDeparture', data['expectedArrival']))
        
        if has_overlapping_visit(visitorId, arrival, new_end):
            return error_response('Visitor already has an overlapping visit.', 409)
            
        # Support group visits
        visitor_ids = data.get('visitorIds', [visitorId])
        visitor_obj_ids = [ObjectId(v) for v in visitor_ids]
        company_obj_id = ObjectId(data['companyId'])
        host_obj_id = ObjectId(data['hostEmployeeId'])
        
        # Determine approval
        approved = bool(data.get('approved'))
        
        # Create visit document using build_visit_doc
        visit_doc = build_visit_doc(
            visitor_obj_ids[0] if len(visitor_obj_ids) == 1 else visitor_obj_ids,
            company_obj_id,
            host_obj_id,
            data.get('purpose', ''),
            arrival,
            new_end,
            approved=approved
        )
        visit_doc['accessAreas'] = data.get('accessAreas', [])
        visit_doc['visitType'] = data.get('visitType', 'single')
        
        result = visit_collection.insert_one(visit_doc)
        visit_id = result.inserted_id
        
        # Get visitor and host information for QR code
        visitor = visitor_collection.find_one({'_id': visitor_obj_ids[0]})
        host = employee_collection.find_one({'_id': host_obj_id})
        
        # Generate visit pass with QR code
        img_byte_arr = generate_visitor_pass(visitor, host, data, visit_id, arrival, new_end)
        
        # Store in GridFS with TTL
        ttl_dt = new_end if new_end else arrival
        qr_id = visitor_image_fs.put(
            img_byte_arr,
            filename=f"visit_pass_{str(visit_id)}.png",
            metadata={
                'type': 'visit_pass',
                'visitId': str(visit_id),
                'timestamp': get_current_utc(),
                'ttl': ttl_dt
            }
        )
        
        # Store qrCode as ObjectId
        visit_collection.update_one({'_id': visit_id}, {'$set': {'qrCode': qr_id}})
        
        # Update each visitor's visits list
        for vid in visitor_obj_ids:
            visitor_collection.update_one(
                {'_id': vid},
                {'$push': {'visits': str(visit_id)}}
            )
            
        # Prepare response with all ObjectIds as strings
        visit_doc = visit_collection.find_one({'_id': visit_id})
        visit_dict = {}
        for key, value in visit_doc.items():
            if isinstance(value, ObjectId):
                visit_dict[key] = str(value)
            elif isinstance(value, list) and all(isinstance(item, ObjectId) for item in value):
                visit_dict[key] = [str(item) for item in value]
            elif isinstance(value, datetime):
                visit_dict[key] = format_datetime(value)
            else:
                visit_dict[key] = value
                
        return jsonify({
            'message': 'Visit scheduled successfully',
            'visit': visit_dict
        }), 201
        
    except Exception as e:
        print(f"Error in schedule_visit: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/visits/<visitId>/check-in', methods=['POST'])
def check_in():
    try:
        visit_id = request.view_args['visitId']
        data = request.json or {}
        
        if 'checkInMethod' not in data:
            return error_response('Check-in method is required.', 400)

        visit = visit_collection.find_one({'visitId': visit_id})
        if not visit:
            return error_response('Visit not found.', 404)

        if visit['status'] != 'scheduled':
            return error_response('Visit is not in scheduled state.', 400)

        # Update visit status
        visit_collection.update_one(
            {'visitId': visit_id},
            {
                '$set': {
                    'status': 'checked_in',
                    'checkInMethod': data['checkInMethod'],
                    'actualArrival': get_current_utc(),
                    'lastUpdated': get_current_utc()
                }
            }
        )

        return jsonify({
            'message': 'Check-in successful',
            'visitId': visit_id
        }), 200

    except Exception as e:
        print(f"Error in check_in: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/visits/<visitId>/check-out', methods=['POST'])
def check_out():
    try:
        visit_id = request.view_args['visitId']
        data = request.json or {}
        
        if 'checkOutMethod' not in data:
            return error_response('Check-out method is required.', 400)

        visit = visit_collection.find_one({'visitId': visit_id})
        if not visit:
            return error_response('Visit not found.', 404)

        if visit['status'] != 'checked_in':
            return error_response('Visit is not checked in.', 400)

        # Update visit status
        visit_collection.update_one(
            {'visitId': visit_id},
            {
                '$set': {
                    'status': 'checked_out',
                    'checkOutMethod': data['checkOutMethod'],
                    'actualDeparture': get_current_utc(),
                    'lastUpdated': get_current_utc()
                }
            }
        )

        return jsonify({
            'message': 'Check-out successful',
            'visitId': visit_id
        }), 200

    except Exception as e:
        print(f"Error in check_out: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('', methods=['GET'])
def get_visitors():
    try:
        company_id = request.args.get('companyId')
        fetch_embeddings = request.args.get('fetchEmbeddings', 'false').lower() == 'true'
        if not company_id:
            return error_response('companyId is required', 400)

        query = {'companyId': ObjectId(company_id)}
        visitors = list(visitor_collection.find(query))
        base_url = request.url_root.rstrip('/') + '/bharatlytics/v1'
        for visitor in visitors:
            visitor['_id'] = str(visitor['_id'])
            visitor['companyId'] = str(visitor['companyId'])
            # Add embedding download links if requested
            if fetch_embeddings:
                visitor['visitorEmbeddings'] = visitor.get('visitorEmbeddings', {})
                emb_dict = visitor['visitorEmbeddings']
                for model, emb in emb_dict.items():
                    if emb.get('embeddingId'):
                        emb['downloadUrl'] = f"{base_url}/visitors/embeddings/{emb['embeddingId']}"
        return jsonify({'visitors': visitors}), 200
    except Exception as e:
        print(f"Error in get_visitors: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/visits', methods=['GET'])
def get_visits():
    try:
        company_id = request.args.get('companyId')
        visitor_id = request.args.get('visitorId')
        status = request.args.get('status')

        query = {}
        if company_id:
            query['companyId'] = ObjectId(company_id)
        if visitor_id:
            query['visitorId'] = ObjectId(visitor_id)
        if status:
            query['status'] = status

        visits = list(visit_collection.find(query))
        
        for visit in visits:
            # Convert all ObjectId fields to strings
            visit['_id'] = str(visit['_id'])
            visit['companyId'] = str(visit['companyId'])
            if isinstance(visit.get('visitorId'), ObjectId):
                visit['visitorId'] = str(visit['visitorId'])
            elif isinstance(visit.get('visitorId'), list):
                visit['visitorId'] = [str(v) for v in visit['visitorId']]
            if isinstance(visit.get('hostEmployeeId'), ObjectId):
                visit['hostEmployeeId'] = str(visit['hostEmployeeId'])
            if isinstance(visit.get('qrCode'), ObjectId):
                visit['qrCode'] = str(visit['qrCode'])
                visit['qrCodeUrl'] = f"/bharatlytics/v1/visits/qr/{visit['_id']}"

        return jsonify({'visits': visits}), 200

    except Exception as e:
        print(f"Error in get_visits: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/visits/qr/<visitId>', methods=['GET'])
def get_visit_qr(visitId):
    try:
        visit = visit_collection.find_one({'_id': ObjectId(visitId)})
        if not visit or not visit.get('qrCode'):
            return error_response('QR code not found', 404)

        qr_file = visitor_image_fs.get(ObjectId(visit['qrCode']))
        return Response(
            qr_file.read(),
            mimetype='image/png',
            headers={'Content-Disposition': f'inline; filename=qr_{visitId}.png'}
        )

    except Exception as e:
        print(f"Error in get_visit_qr: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/cleanup-duplicates', methods=['POST'])
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
        to_delete = visitor_collection.find({
            "companyId": ObjectId(company_id),
            "status": "pending_duplicate_removal",
            "visitorEmbeddings.buffalo_l.finishedAt": {"$lt": cutoff}
        })
        
        count = 0
        for visitor in to_delete:
            print(f"[Cleanup] Deleting visitor {visitor['visitorId']} in {visitor['companyId']} (pending_duplicate_removal > {hours}h)")
            visitor_collection.delete_one({"_id": visitor["_id"]})
            count += 1
            
        return jsonify({
            'message': f'Successfully cleaned up {count} duplicate visitors',
            'deleted_count': count,
            'hours_threshold': hours,
            'companyId': company_id
        }), 200
        
    except Exception as e:
        print(f"Error in cleanup_duplicates: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/<visitorId>/embeddings', methods=['GET'])
def get_visitor_embeddings():
    try:
        visitor_id = request.view_args['visitorId']
        company_id = request.args.get('companyId')
        if not company_id:
            return error_response('companyId is required', 400)

        visitor = visitor_collection.find_one({
            'companyId': ObjectId(company_id),
            'visitorId': visitor_id
        })
        if not visitor:
            return error_response('Visitor not found', 404)

        embeddings = visitor.get('visitorEmbeddings', {})
        return jsonify({
            'visitorId': visitor_id,
            'companyId': company_id,
            'embeddings': embeddings
        }), 200

    except Exception as e:
        print(f"Error in get_visitor_embeddings: {e}")
        return error_response(str(e), 500)

def validate_visitor_data(data):
    """Validate visitor-specific fields."""
    errors = []
    
    # Validate visitor type
    if data.get('visitorType') and data['visitorType'] not in ['individual', 'group', 'contractor']:
        errors.append('Invalid visitor type. Must be one of: individual, group, contractor')
    
    # Validate ID type
    if data.get('idType') and data['idType'] not in ['passport', 'driving_license', 'aadhar', 'pan_card']:
        errors.append('Invalid ID type. Must be one of: passport, driving_license, aadhar, pan_card')
    
    # Validate ID number format based on type
    if data.get('idType') and data.get('idNumber'):
        if data['idType'] == 'aadhar' and not re.match(r'^\d{12}$', data['idNumber']):
            errors.append('Invalid Aadhar number format. Must be 12 digits')
        elif data['idType'] == 'pan_card' and not re.match(r'^[A-Z]{5}\d{4}[A-Z]{1}$', data['idNumber']):
            errors.append('Invalid PAN card format')
        elif data['idType'] == 'driving_license' and not re.match(r'^[A-Z]{2}\d{2}\d{4}\d{7}$', data['idNumber']):
            errors.append('Invalid driving license format')
    
    # Validate expected arrival/departure
    if data.get('expectedArrival') and data.get('expectedDeparture'):
        try:
            arrival_str = data['expectedArrival'].replace('Z', '+00:00')
            arrival = datetime.fromisoformat(arrival_str)
            departure = datetime.fromisoformat(data['expectedDeparture'].replace('Z', '+00:00'))
            if departure <= arrival:
                errors.append('Expected departure must be after expected arrival')
        except ValueError:
            errors.append('Invalid date format for expected arrival/departure')
    
    return errors 

@visitor_bp.route('/visits/<visitId>', methods=['PATCH'])
def update_visit(visitId):
    try:
        data = request.json or {}
        update_fields = {}
        for field in ['purpose', 'expectedArrival', 'expectedDeparture', 'accessAreas', 'visitType', 'status']:
            if field in data:
                update_fields[field] = data[field]
        if not update_fields:
            return error_response('No valid fields to update.', 400)
        visit = visit_collection.find_one({'visitId': visitId})
        if not visit:
            return error_response('Visit not found.', 404)
        # Overlap check if changing times
        if 'expectedArrival' in update_fields or 'expectedDeparture' in update_fields:
            visitor_id = visit['visitorId'] if isinstance(visit['visitorId'], str) else visit['visitorId'][0]
            new_start_str = update_fields.get('expectedArrival', visit['expectedArrival'])
            new_end_str = update_fields.get('expectedDeparture', visit.get('expectedDeparture', visit['expectedArrival']))
            new_start_str = new_start_str.replace('Z', '+00:00')
            new_end_str = new_end_str.replace('Z', '+00:00')
            new_start = datetime.fromisoformat(new_start_str)
            new_end = datetime.fromisoformat(new_end_str)
            if has_overlapping_visit(visitor_id, new_start, new_end):
                return error_response('Visitor already has an overlapping visit.', 409)
        visit_collection.update_one({'visitId': visitId}, {'$set': update_fields})
        return jsonify({'message': 'Visit updated successfully'}), 200
    except Exception as e:
        print(f"Error in update_visit: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/visits/<visitId>', methods=['DELETE'])
def delete_visit(visitId):
    try:
        visit = visit_collection.find_one({'visitId': visitId})
        if not visit:
            return error_response('Visit not found.', 404)
        visit_collection.update_one({'visitId': visitId}, {'$set': {'status': 'cancelled', 'cancelledAt': get_current_utc()}})
        return jsonify({'message': 'Visit cancelled successfully'}), 200
    except Exception as e:
        print(f"Error in delete_visit: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/visits/analytics/host', methods=['GET'])
def visits_per_host():
    try:
        company_id = request.args.get('companyId')
        pipeline = [
            {"$match": {"companyId": ObjectId(company_id)}},
            {"$group": {"_id": "$hostEmployeeId", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        result = list(visit_collection.aggregate(pipeline))
        return jsonify(result)
    except Exception as e:
        print(f"Error in visits_per_host: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/visits/analytics/area', methods=['GET'])
def visits_per_area():
    try:
        company_id = request.args.get('companyId')
        pipeline = [
            {"$match": {"companyId": ObjectId(company_id)}},
            {"$unwind": "$accessAreas"},
            {"$group": {"_id": "$accessAreas", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        result = list(visit_collection.aggregate(pipeline))
        return jsonify(result)
    except Exception as e:
        print(f"Error in visits_per_area: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/visits/verify-qr', methods=['POST'])
def verify_qr():
    try:
        # Check if file is present in request
        if 'qrCode' not in request.files:
            print("Debug: Files in request:", request.files)
            return error_response('QR code image is required', 400)
            
        qr_file = request.files['qrCode']
        if not qr_file or qr_file.filename == '':
            return error_response('No file selected', 400)
            
        access_zone = request.form.get('accessZone')
        
        try:
            # Read QR code image
            qr_img = Image.open(qr_file.stream)
            # Convert to grayscale if needed
            if qr_img.mode != 'L':
                qr_img = qr_img.convert('L')

            # Create a QR code reader
            qr = qrcode.QRCode()
            
            # Convert PIL Image to binary data
            img_byte_arr = io.BytesIO()
            qr_img.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()

            try:
                qr.add_data(img_byte_arr)
                qr.make()
                visit_id = qr.data.decode('utf-8')
            except Exception:
                return error_response('Could not decode QR code', 400)
                
            if not visit_id:
                return error_response('Invalid QR code format', 400)
                
            # Find visit in database
            visit = visit_collection.find_one({'_id': ObjectId(visit_id)})
            if not visit:
                return error_response('Visit not found', 404)
                
            # Check if visit is in valid state
            if visit['status'] not in ['scheduled', 'checked_in']:
                return error_response('Visit is not in a valid state', 400)
                
            # Check time validity using UTC
            current_time = get_current_utc()
            expected_arrival = visit['expectedArrival']
            expected_departure = visit.get('expectedDeparture', expected_arrival)

            # Ensure all datetimes are timezone-aware (UTC)
            if expected_arrival.tzinfo is None:
                expected_arrival = expected_arrival.replace(tzinfo=timezone.utc)
            if expected_departure.tzinfo is None:
                expected_departure = expected_departure.replace(tzinfo=timezone.utc)

            if current_time < expected_arrival:
                return error_response('Visit has not started yet', 400)
            if current_time > expected_departure:
                return error_response('Visit has expired', 400)
                
            # Check access zone if provided
            if access_zone and visit.get('accessAreas'):
                if access_zone not in visit['accessAreas']:
                    return error_response('QR code not valid for this access zone', 400)
                    
            # Convert all fields to JSON-serializable format
            visit_dict = {}
            for key, value in visit.items():
                if isinstance(value, ObjectId):
                    visit_dict[key] = str(value)
                elif isinstance(value, list) and all(isinstance(item, ObjectId) for item in value):
                    visit_dict[key] = [str(item) for item in value]
                elif isinstance(value, datetime):
                    visit_dict[key] = format_datetime(value)
                else:
                    visit_dict[key] = value
                    
            return jsonify({
                'message': 'QR code is valid',
                'visit': visit_dict
            }), 200
            
        except Exception as e:
            print(f"Error processing QR code: {e}")
            return error_response(f'Error processing QR code: {str(e)}', 400)
            
    except Exception as e:
        print(f"Error in verify_qr: {e}")
        return error_response(str(e), 500)

@visitor_bp.route('/embeddings/<embedding_id>', methods=['GET'])
def serve_visitor_embedding(embedding_id):
    try:
        print(f"Attempting to fetch visitor embedding: {embedding_id}")
        try:
            file = visitor_embedding_fs.get(ObjectId(embedding_id))
            print(f"Successfully found visitor embedding file")
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
        except Exception as e:
            print(f"Error fetching visitor embedding file: {e}")
            return error_response('Embedding not found', 404)
    except Exception as e:
        print(f"Error in serve_visitor_embedding: {e}")
        return error_response('Error serving embedding', 500) 