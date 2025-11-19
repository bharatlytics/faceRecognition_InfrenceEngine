# Bharatlytics API Documentation

## Table of Contents
1. [Overview](#overview)
2. [Base URL and Authentication](#base-url-and-authentication)
3. [Core Modules](#core-modules)
   - [Employee Management](#employee-management)
   - [Company Management](#company-management)
   - [Visitor Management](#visitor-management)
   - [Entity Hierarchy Management](#entity-hierarchy-management)
4. [End-to-End Workflows](#end-to-end-workflows)
5. [Security & Best Practices](#security--best-practices)
6. [Rate Limiting & Performance](#rate-limiting--performance)

## Overview

The Bharatlytics API provides a comprehensive suite of endpoints for managing various aspects of enterprise operations, including employee management, company structures, visitor tracking, and organizational hierarchies. This documentation covers all available endpoints, their usage, and common workflows.

## Base URL and Authentication

### Base URL
All API endpoints are prefixed with `/bharatlytics/v1`

### Authentication
All endpoints require authentication using JWT tokens:
```http
Authorization: Bearer <your_token>
```

## Core Modules

### Employee Management

#### Key Features
- Complete employee lifecycle management
- Image and embedding handling for facial recognition
- Reporting structure and hierarchy
- Company-based data isolation

#### Common Workflows

1. **New Employee Onboarding**
```http
# 1. Register employee with basic details
POST /employees/register
Content-Type: multipart/form-data
{
    "employeeId": "EMP001",
    "employeeName": "John Doe",
    "companyId": "COMP001",
    "employeeEmail": "john@company.com",
    "employeeMobile": "1234567890",
    "employeeDesignation": "Software Engineer",
    "images": {
        "front": <image_file>,
        "side": <image_file>
    }
}

# 2. Set reporting manager
PATCH /employees/update
{
    "employeeId": "EMP001",
    "companyId": "COMP001",
    "employeeReportingId": "EMP002"
}

# 3. Link to entity hierarchy
POST /entities/{entity_id}/employees
{
    "employeeId": "EMP001"
}
```

2. **Employee Transfer Workflow**
```http
# 1. Update reporting structure
PATCH /employees/update
{
    "employeeId": "EMP001",
    "companyId": "COMP001",
    "employeeReportingId": "EMP003"
}

# 2. Update entity assignment
POST /entities/{new_entity_id}/employees
{
    "employeeId": "EMP001"
}
```

### Company Management

#### Key Features
- Company profile management
- Multi-branch support
- Customizable company settings
- Integration with other modules

#### Common Workflows

1. **New Company Setup**
```http
# 1. Create company profile
POST /companies
{
    "companyName": "Tech Corp",
    "hqAddress": "123 Tech Street",
    "hqEmail": "admin@techcorp.com",
    "website": "www.techcorp.com",
    "phone": "+1234567890"
}

# 2. Set up initial entity hierarchy
POST /entities/templates/{template_id}/clone
{
    "companyId": "COMP001",
    "namePrefix": "TechCorp-"
}

# 3. Add admin users
PATCH /companies/{company_id}
{
    "adminUsers": ["USER001", "USER002"]
}
```

### Visitor Management

#### Key Features
- Visitor registration and tracking
- Visit scheduling
- QR code-based check-in/out
- Security and compliance

#### Common Workflows

1. **Scheduled Visit Process**
```http
# 1. Register visitor
POST /visitors/register
Content-Type: multipart/form-data
{
    "visitorName": "Alice Smith",
    "phone": "9876543210",
    "companyId": "COMP001",
    "hostEmployeeId": "EMP001",
    "face_images": {
        "center": <image_file>,
        "left": <image_file>,
        "right": <image_file>
    }
}

# 2. Schedule visit
POST /visitors/{visitor_id}/schedule-visit
{
    "companyId": "COMP001",
    "hostEmployeeId": "EMP001",
    "expectedArrival": "2024-03-20T10:00:00Z",
    "expectedDeparture": "2024-03-20T17:00:00Z",
    "purpose": "Client Meeting",
    "accessAreas": ["Reception", "Meeting Room 1"]
}

# 3. Check-in process
POST /visits/{visit_id}/check-in
{
    "checkInMethod": "qr_code",
    "qrData": "VISIT_QR_DATA"
}

# 4. Check-out process
POST /visits/{visit_id}/check-out
{
    "checkOutMethod": "face_recognition"
}
```

### Entity Hierarchy Management

#### Key Features
- Flexible organizational structure
- Template-based hierarchy creation
- Employee-entity mapping
- Asset management

#### Common Workflows

1. **Manufacturing Plant Setup**
```http
# 1. Clone manufacturing template
POST /entities/templates/manufacturing/clone
{
    "companyId": "COMP001",
    "namePrefix": "Plant1-"
}

# 2. Customize departments
POST /entities
{
    "name": "Quality Control",
    "type": "department",
    "parentId": "PLANT001",
    "companyId": "COMP001",
    "metadata": {
        "capacity": 50,
        "shift_count": 3
    }
}

# 3. Link department head
POST /entities/{department_id}/employees
{
    "employeeId": "EMP001"
}

# 4. Set up workstations
POST /entities
{
    "name": "QC Station 1",
    "type": "workstation",
    "parentId": "DEPT001",
    "companyId": "COMP001",
    "metadata": {
        "equipment": ["Scanner", "Testing Kit"]
    }
}
```

## Security & Best Practices

### Data Protection
1. All sensitive data is encrypted at rest
2. PII is handled according to GDPR guidelines
3. Image data is stored securely with access controls

### Best Practices
1. Use appropriate HTTP methods (GET, POST, PATCH, DELETE)
2. Include proper error handling
3. Implement retry mechanisms for failed operations
4. Cache responses where appropriate

### Error Handling
All endpoints return standardized error responses:
```json
{
    "error": "Error description",
    "code": "ERROR_CODE",
    "details": {
        "field": "error details"
    }
}
```

## Rate Limiting & Performance

### Rate Limits
- 100 requests per minute per IP
- 1000 requests per hour per company
- 10000 requests per day per company

### Performance Guidelines
1. Use pagination for large datasets
2. Implement caching where appropriate
3. Optimize image uploads
4. Use appropriate indexes for queries

## End-to-End Workflows

1. **Visitor Registration**
   - Client submits visitor details and three face images (left, right, center)
   - System validates input data and images
   - Face images are stored in GridFS
   - Embedding job is queued for facial recognition
   - System checks for duplicate faces
   - Registration is marked as complete or pending based on embedding status
   - System returns MongoDB ObjectId as visitor identifier

2. **Visit Scheduling**
   - Host employee schedules visit for a registered visitor or group of visitors
   - System validates for overlapping visits (no two visits for the same visitor can overlap in time)
   - System generates a unique QR code for this specific visit
   - **QR code encodes:**
     - `visitId`
     - `expectedArrival` and `expectedDeparture` (valid time range)
     - `accessAreas` (allowed areas for this visit)
   - QR code is stored in GridFS
   - Visit record is created with scheduled status
   - QR code is made available for check-in

3. **Check-in Process**
   - Visitor arrives at premises
   - System verifies visitor identity using:
     - QR code scan (QR code is only valid within the visit's time range and for the specified access areas)
     - Facial recognition
     - Manual verification
   - Visit status is updated to checked-in
   - Actual arrival time is recorded

4. **Check-out Process**
   - Visitor completes visit
   - System verifies visitor identity
   - Visit status is updated to checked-out
   - Actual departure time is recorded

5. **Duplicate Management**
   - System detects duplicate registrations
   - Duplicate records are marked for removal
   - Cleanup process removes old duplicates
   - New registrations are prevented for duplicates

## Security & Best Practices

### Data Protection
1. All sensitive data is encrypted at rest
2. PII is handled according to GDPR guidelines
3. Image data is stored securely with access controls

### Best Practices
1. Use appropriate HTTP methods (GET, POST, PATCH, DELETE)
2. Include proper error handling
3. Implement retry mechanisms for failed operations
4. Cache responses where appropriate

### Error Handling
All endpoints return standardized error responses:
```json
{
    "error": "Error description",
    "code": "ERROR_CODE",
    "details": {
        "field": "error details"
    }
}
```

## Rate Limiting & Performance

### Rate Limits
- 100 requests per minute per IP
- 1000 requests per hour per company
- 10000 requests per day per company

### Performance Guidelines
1. Use pagination for large datasets
2. Implement caching where appropriate
3. Optimize image uploads
4. Use appropriate indexes for queries

## Security & Best Practices

### Data Protection
1. All sensitive data is encrypted at rest
2. PII is handled according to GDPR guidelines
3. Image data is stored securely with access controls

### Best Practices
1. Use appropriate HTTP methods (GET, POST, PATCH, DELETE)
2. Include proper error handling
3. Implement retry mechanisms for failed operations
4. Cache responses where appropriate

### Error Handling
All endpoints return standardized error responses:
```json
{
    "error": "Error description",
    "code": "ERROR_CODE",
    "details": {
        "field": "error details"
    }
}
```

## Rate Limiting & Performance

### Rate Limits
- 100 requests per minute per IP
- 1000 requests per hour per company
- 10000 requests per day per company

### Performance Guidelines
1. Use pagination for large datasets
2. Implement caching where appropriate
3. Optimize image uploads
4. Use appropriate indexes for queries

# Employee Management API Documentation

This document provides comprehensive information about the Employee Management API endpoints, including detailed schemas, best practices, and implementation guidelines.

## Table of Contents
1. [Overview](#overview)
2. [Base URL and Authentication](#base-url-and-authentication)
3. [API Endpoints](#api-endpoints)
4. [Data Schemas](#data-schemas)
5. [Best Practices](#best-practices)
6. [Error Handling](#error-handling)
7. [Rate Limiting](#rate-limiting)
8. [Security Considerations](#security-considerations)
9. [Security & Abuse Protection](#security-abuse-protection)

## Overview

The Employee Management API provides endpoints for managing employee records, including registration, retrieval, updates, and deletion. The API supports image and embedding management for employee identification.

### Key Features
- Employee registration with image upload
- Embedding generation and management
- Soft and hard delete options
- Duplicate detection and cleanup
- Flexible querying with field selection

## Base URL and Authentication

### Base URL
All API endpoints are prefixed with `/bharatlytics/v1`

### Authentication
*Note: Authentication details should be added based on your implementation*

## API Endpoints

### 1. Register Employee
Register a new employee with their details and images.

**Endpoint:** `POST /employees/register`

**Request Format:**
- Content-Type: `multipart/form-data`

**Required Fields:**
- `employeeId` (string, max length: 50): Unique identifier for the employee
  - Must be alphanumeric
  - Cannot contain special characters except underscore and hyphen
- `employeeName` (string, max length: 100): Name of the employee
  - Must contain at least one character
  - Can contain spaces
- `companyId` (string, max length: 50): Company identifier
  - Must be alphanumeric
  - Cannot contain special characters except underscore and hyphen

**Optional Fields:**
- `gender` (string, enum: ["male", "female", "other"]): Employee's gender
- `joiningDate` (string, format: "YYYY-MM-DD"): Date of joining
- `employeeEmail` (string, format: email): Employee's email address
  - Must be unique within the company
  - Must follow standard email format
- `employeeMobile` (string, pattern: "^[0-9]{10}$"): Employee's mobile number
  - Must be exactly 10 digits
  - Must be unique within the company
- `employeeDesignation` (string, max length: 100): Employee's designation
- `employeeReportingId` (string, max length: 50): ID of the reporting manager
  - Must be a valid employee ID in the system
- `status` (string, enum: ["active", "inactive", "pending"]): Employee status
- `blacklisted` (boolean, default: false): Whether employee is blacklisted

**Required Files:**
- Image files for all required poses:
  - Format: JPEG
  - Maximum size: 5MB per image
  - Minimum resolution: 640x480
  - Required poses: front, side
  - File naming: `{pose}.jpg`

**Optional Parameters:**
- `embeddingAttached` (boolean, default: false): Whether embedding is attached
- `embeddingVersion` (string, enum: ["buffalo_l"]): Version of embedding model

**Response:**
```json
{
    "message": "Employee registration queued",
    "employeeId": "string",
    "embeddingStatus": {
        "buffalo_l": "queued"
    }
}
```

**Pros:**
- Supports both synchronous and asynchronous embedding generation
- Handles duplicate detection
- Validates all input fields
- Supports multiple image poses

**Cons:**
- Requires multiple image uploads
- Embedding generation may take time
- No batch registration support

### 2. Get Employee Details
Retrieve employee information.

**Endpoint:** `GET /employees`

**Query Parameters:**
- `companyId` (required, string): Company identifier
- `employeeId` (optional, string): Specific employee ID
- `fetchEmbeddings` (optional, boolean, default: false): Whether to include embeddings
- `embeddingVersion` (optional, string): Specific embedding version to fetch
- `fetchImages` (optional, boolean, default: false): Whether to include image URLs
- `fields` (optional, string): Comma-separated list of fields to return
  - Example: "employeeId,employeeName,status"
  - Default: all fields

**Response Schema:**
```json
[
    {
        "employeeId": "string",
        "companyId": "string",
        "employeeName": "string",
        "gender": "string",
        "joiningDate": "string",
        "employeeEmail": "string",
        "employeeMobile": "string",
        "employeeDesignation": "string",
        "employeeReportingId": "string",
        "status": "string",
        "blacklisted": boolean,
        "employeeImages": {
            "front": "string",
            "side": "string"
        },
        "employeeEmbeddings": {
            "buffalo_l": {
                "status": "string",
                "embeddingId": "string"
            }
        },
        "createdAt": "string",
        "lastUpdated": "string"
    }
]
```

**Pros:**
- Flexible field selection
- Supports partial data retrieval
- Efficient pagination
- Caching support

**Cons:**
- Large response size with images/embeddings
- No bulk retrieval optimization

### 3. Get Employee Image
Retrieve an employee's image.

**Endpoint:** `GET /employees/images/{image_id}`

**Path Parameters:**
- `image_id` (required, string): MongoDB ObjectId of the image

**Response:**
- Content-Type: `image/jpeg`
- Returns the image file

**Pros:**
- Direct image serving
- Caching support
- Efficient delivery

**Cons:**
- No image resizing options
- No format conversion

### 4. Get Employee Embedding
Retrieve an employee's embedding data.

**Endpoint:** `GET /employees/embeddings/{embedding_id}`

**Path Parameters:**
- `embedding_id` (required, string): MongoDB ObjectId of the embedding

**Response:**
- Content-Type: `application/octet-stream`
- Returns the embedding file

**Pros:**
- Direct embedding access
- Efficient binary transfer
- Secure access

**Cons:**
- No embedding format conversion
- Large file size

### 5. Update Employee
Update employee information.

**Endpoint:** `PATCH /employees/update`

**Request Format:**
- Content-Type: `application/json` or `multipart/form-data`

**Required Fields:**
- `employeeId` (string): Employee identifier
- `companyId` (string): Company identifier

**Optional Fields:**
- `employeeName` (string, max length: 100)
- `gender` (string, enum: ["male", "female", "other"])
- `blacklisted` (boolean)
- `joiningDate` (string, format: "YYYY-MM-DD")
- `status` (string, enum: ["active", "inactive", "pending"])
- `employeeEmail` (string, format: email)
- `employeeMobile` (string, pattern: "^[0-9]{10}$")
- `employeeDesignation` (string, max length: 100)
- `employeeReportingId` (string, max length: 50)

**Response:**
```json
{
    "message": "Employee updated successfully"
}
```

**Pros:**
- Partial updates supported
- Field validation
- Atomic updates

**Cons:**
- No batch update support
- No image update support

### 6. Delete Employee
Delete an employee record.

**Endpoint:** `DELETE /employees/delete`

**Request Format:**
- Content-Type: `application/json` or `multipart/form-data`

**Required Fields:**
- `employeeId` (string): Employee identifier
- `companyId` (string): Company identifier

**Optional Fields:**
- `mode` (string, enum: ["soft", "hard"], default: "soft"): Delete mode
- `reason` (string, max length: 200, default: "user_request"): Reason for deletion

**Response:**
```json
{
    "message": "Employee soft deleted (archived) successfully"
}
```

**Pros:**
- Soft delete option
- Reason tracking
- Cascading deletion support

**Cons:**
- No batch delete
- No undo option for hard delete

### 7. Cleanup Duplicates
Clean up duplicate employee records.

**Endpoint:** `POST /employees/cleanup-duplicates`

**Request Format:**
- Content-Type: `multipart/form-data`

**Required Fields:**
- `companyId` (string): Company identifier

**Optional Fields:**
- `hours` (integer, min: 1, max: 168, default: 24): Hours threshold for cleanup

**Response:**
```json
{
    "message": "Successfully cleaned up X duplicate employees",
    "deleted_count": 0,
    "hours_threshold": 24,
    "companyId": "string"
}
```

**Pros:**
- Automated cleanup
- Configurable time threshold
- Safe deletion

**Cons:**
- No selective cleanup
- No preview of deletions

### 8. /audit-logs (Admin Only)

**Endpoint:** `GET /audit-logs`

**Authentication:**
- Requires `X-Auth-Token` header (replace with your real logic).
- Only accessible to admins (add your own admin check as needed).

**Query Parameters:**
- `employeeId` (optional): Filter logs by employee ID
- `companyId` (optional): Filter logs by company ID

**Response:**
```json
[
  {
    "_id": "string",
    "user": "string",
    "timestamp": "ISO8601 string",
    "action": "register|update|delete",
    "employeeId": "string",
    "companyId": "string",
    "before": { ... },
    "after": { ... }
  }
]
```

**Errors:**
- `401 Unauthorized` if missing or invalid auth token
- `429 Too Many Requests` if rate limit exceeded

## Data Schemas

### Employee Schema
```json
{
    "employeeId": "string",
    "companyId": "string",
    "employeeName": "string",
    "gender": "string",
    "joiningDate": "string",
    "employeeEmail": "string",
    "employeeMobile": "string",
    "employeeDesignation": "string",
    "employeeReportingId": "string",
    "status": "string",
    "blacklisted": boolean,
    "employeeImages": {
        "front": "ObjectId",
        "side": "ObjectId"
    },
    "employeeEmbeddings": {
        "buffalo_l": {
            "status": "string",
            "embeddingId": "ObjectId",
            "queuedAt": "datetime",
            "finishedAt": "datetime"
        }
    },
    "createdAt": "datetime",
    "lastUpdated": "datetime",
    "deletedAt": "datetime",
    "deletedReason": "string"
}
```

## Best Practices

### Image Handling
1. Use JPEG format for all images
2. Maintain aspect ratio
3. Ensure good lighting
4. Use consistent background
5. Follow pose guidelines

### Embedding Generation
1. Use supported model versions
2. Monitor generation status
3. Handle failures gracefully
4. Implement retry mechanism

### Data Validation
1. Validate all input fields
2. Check for duplicates
3. Sanitize user input
4. Handle special characters

### Error Handling
1. Use appropriate status codes
2. Provide clear error messages
3. Log errors for debugging
4. Implement retry mechanisms

## Error Responses

All endpoints may return the following error responses:

```json
{
    "error": "Error message",
    "status": 400,
    "details": {
        "field": "error description"
    }
}
```

Common HTTP Status Codes:
- 200: Success
- 400: Bad Request
- 404: Not Found
- 409: Conflict
- 500: Internal Server Error

## Rate Limiting

- 100 requests per minute per IP
- 1000 requests per hour per company
- 10000 requests per day per company

## Security Considerations

1. Always use HTTPS
2. Implement proper authentication
3. Validate all input
4. Sanitize file uploads
5. Implement rate limiting
6. Use secure headers
7. Monitor for abuse
8. Regular security audits

## Security & Abuse Protection

### Rate Limiting
- All API endpoints are protected by rate limiting.
- Default: 100 requests per IP per 60 seconds.
- If the limit is exceeded, the API returns HTTP 429 Too Many Requests.
- All rate limit events are logged to the `securityLogs` collection.

### Authentication
- Sensitive endpoints require authentication.
- Example: `/audit-logs` requires an `X-Auth-Token` header (replace with your real logic).
- Unauthorized access attempts are logged to the `securityLogs` collection and return HTTP 401 Unauthorized.

### Security Logging
- All rate limit and unauthorized access attempts are logged to the `securityLogs` collection for monitoring and audit.

## Notes

1. All timestamps are in UTC
2. Image files must be in JPEG format
3. Email addresses must be unique within a company
4. Phone numbers must be 10 digits and unique within a company
5. Soft delete marks the employee as archived but retains the data
6. Hard delete permanently removes all employee data including images and embeddings
7. Embedding generation is asynchronous
8. All IDs are case-sensitive
9. Maximum file size is 5MB per image
10. Maximum request size is 10MB

## Company Management API

### 1. Create Company
Create a new company.

**Endpoint:** `POST /bharatlytics/v1/companies`

**Request Format:**
- Content-Type: `application/json`

**Required Fields:**
- `companyName` (string): Name of the company

**Optional Fields:**
- `status` (string): Status of the company
- `logo` (string): URL of the company logo
- `colorScheme` (string): Color scheme of the company
- `hqAddress` (string): Headquarters address
- `hqEmail` (string): Headquarters email
- `website` (string): Company website
- `phone` (string): Contact phone number
- `designations` (array): List of designations
- `infrastructure` (object): Infrastructure details
- `adminUsers` (array): List of admin users

**Response:**
```json
{
    "message": "Company created",
    "company": {
        "_id": "string",
        "companyName": "string",
        "createdAt": "string",
        "lastUpdated": "string",
        "status": "string",
        "logo": "string",
        "colorScheme": "string",
        "hqAddress": "string",
        "hqEmail": "string",
        "website": "string",
        "phone": "string",
        "designations": [],
        "infrastructure": {},
        "adminUsers": []
    }
}
```

### 2. List Companies
List all companies with optional filtering.

**Endpoint:** `GET /bharatlytics/v1/companies`

**Query Parameters:**
- `name` (optional, string): Filter companies by name
- `status` (optional, string): Filter companies by status

**Response:**
```json
{
    "companies": [
        {
            "_id": "string",
            "companyName": "string",
            "createdAt": "string",
            "lastUpdated": "string",
            "status": "string",
            "logo": "string",
            "colorScheme": "string",
            "hqAddress": "string",
            "hqEmail": "string",
            "website": "string",
            "phone": "string",
            "designations": [],
            "infrastructure": {},
            "adminUsers": []
        }
    ]
}
```

### 3. Get Company
Get details of a specific company by its MongoDB `_id`.

**Endpoint:** `GET /bharatlytics/v1/companies/{companyId}`

**Path Parameters:**
- `companyId` (required, string): MongoDB `_id` of the company

**Response:**
```json
{
    "company": {
        "_id": "string",
        "companyName": "string",
        "createdAt": "string",
        "lastUpdated": "string",
        "status": "string",
        "logo": "string",
        "colorScheme": "string",
        "hqAddress": "string",
        "hqEmail": "string",
        "website": "string",
        "phone": "string",
        "designations": [],
        "infrastructure": {},
        "adminUsers": []
    }
}
```

### 4. Update Company
Update details of a specific company by its MongoDB `_id`.

**Endpoint:** `PATCH /bharatlytics/v1/companies/{companyId}`

**Path Parameters:**
- `companyId` (required, string): MongoDB `_id` of the company

**Request Format:**
- Content-Type: `application/json`

**Optional Fields:**
- `companyName` (string): Name of the company
- `status` (string): Status of the company
- `logo` (string): URL of the company logo
- `colorScheme` (string): Color scheme of the company
- `hqAddress` (string): Headquarters address
- `hqEmail` (string): Headquarters email
- `website` (string): Company website
- `phone` (string): Contact phone number
- `designations` (array): List of designations
- `infrastructure` (object): Infrastructure details
- `adminUsers` (array): List of admin users

**Response:**
```json
{
    "message": "Company updated",
    "company": {
        "_id": "string",
        "companyName": "string",
        "createdAt": "string",
        "lastUpdated": "string",
        "status": "string",
        "logo": "string",
        "colorScheme": "string",
        "hqAddress": "string",
        "hqEmail": "string",
        "website": "string",
        "phone": "string",
        "designations": [],
        "infrastructure": {},
        "adminUsers": []
    }
}
```

### 5. Delete Company
Delete a specific company by its MongoDB `_id`. Admin privileges required.

**Endpoint:** `DELETE /bharatlytics/v1/companies/{companyId}`

**Path Parameters:**
- `companyId` (required, string): MongoDB `_id` of the company

**Response:**
```json
{
    "message": "Company deleted"
}
```

### 6. Seed Company
Add a document for a specific company, e.g., "Bhagwati Product Limited".

**Endpoint:** `POST /bharatlytics/v1/companies/seed`

**Response:**
```json
{
    "message": "Company seeded",
    "company": {
        "_id": "string",
        "companyName": "string",
        "createdAt": "string",
        "lastUpdated": "string",
        "status": "string",
        "logo": "string",
        "colorScheme": "string",
        "hqAddress": "string",
        "hqEmail": "string",
        "website": "string",
        "phone": "string",
        "designations": [],
        "infrastructure": {},
        "adminUsers": []
    }
}
```

## Visitor Management API

The Visitor Management API provides endpoints for managing visitor records, including registration, scheduling visits, check-in/check-out processes, and QR code generation.

### Key Features
- Visitor registration with multiple face images (left, right, center)
- Visit scheduling with QR code generation
- Check-in/check-out management
- Duplicate detection and cleanup
- Optional document management (Aadhar, PAN, driving license)

### API Endpoints

#### 1. Register Visitor
Register a new visitor with their details and face images.

**Endpoint:** `POST /bharatlytics/v1/visitors/register`

**Request Format:**
- Content-Type: `multipart/form-data`

**Required Fields:**
- `companyId` (ObjectId): Company identifier from company collection
- `visitorName` (string, max length: 100): Name of the visitor
- `phone` (string, pattern: "^[0-9]{10}$"): Visitor's phone number
- `hostEmployeeId` (ObjectId): ID of the host employee from employeeInfo collection
- Face images:
  - `face_left` (file): Left pose face image
  - `face_right` (file): Right pose face image
  - `face_center` (file): Center pose face image
    - Format: JPEG
    - Maximum size: 5MB per image
    - Minimum resolution: 640x480

**Optional Fields:**
- `email` (string, format: email): Visitor's email address
- `purpose` (string): Purpose of visit
- `status` (string, enum: ["active", "inactive", "pending"], default: "active"): Visitor status
- `blacklisted` (boolean, default: false): Whether visitor is blacklisted

**Optional Files:**
- `aadhar_card` (file): Aadhar card image
- `pan_card` (file): PAN card image
- `driving_license` (file): Driving license image

**Response:**
```json
{
    "message": "Visitor registration queued",
    "_id": "ObjectId",
    "embeddingStatus": {
        "buffalo_l": "queued"
    }
}
```

#### 2. Schedule Visit
Schedule a visit for a registered visitor or a group of visitors.

**Endpoint:** `POST /bharatlytics/v1/visitors/{visitorId}/schedule-visit`

**Request Format:**
- Content-Type: `application/json`

**Required Fields:**
- `companyId` (ObjectId): Company identifier
- `hostEmployeeId` (ObjectId): ID of the host employee
- `expectedArrival` (string, format: ISO8601): Expected arrival time

**Optional Fields:**
- `expectedDeparture` (string, format: ISO8601): Expected departure time
- `purpose` (string): Purpose of visit
- `visitorIds` (array of ObjectId): For group visits, list of visitor IDs (if omitted, defaults to single visitor)
- `visitType` (string, enum: ["single", "group", "contractor"]): Type of visit
- `accessAreas` (array of string): List of areas the visitor/group is allowed to access

**Validation:**
- The system prevents overlapping visits for the same visitor (no two visits can overlap in time for a visitor with status scheduled/checked_in).

**Response:**
```json
{
    "message": "Visit scheduled successfully",
    "visit": {
        "_id": "ObjectId",
        "visitorId": "ObjectId" or ["ObjectId", ...],
        "companyId": "ObjectId",
        "hostEmployeeId": "ObjectId",
        "purpose": "string",
        "status": "scheduled",
        "expectedArrival": "string",
        "expectedDeparture": "string",
        "visitType": "string",
        "accessAreas": ["string", ...],
        "qrCode": "string",
        "createdAt": "string",
        "lastUpdated": "string"
    }
}
```

#### 3. Update Visit
Update visit details (purpose, timings, access areas, etc.).

**Endpoint:** `PATCH /bharatlytics/v1/visits/{visitId}`

**Request Format:**
- Content-Type: `application/json`

**Updatable Fields:**
- `purpose`, `expectedArrival`, `expectedDeparture`, `accessAreas`, `visitType`, `status`

**Validation:**
- Overlapping visit validation is enforced if timings are changed.

**Response:**
```json
{
    "message": "Visit updated successfully"
}
```

#### 4. Cancel Visit
Cancel (soft delete) a visit.

**Endpoint:** `DELETE /bharatlytics/v1/visits/{visitId}`

**Response:**
```json
{
    "message": "Visit cancelled successfully"
}
```

#### 5. Analytics: Visits per Host
Get the number of visits per host employee.

**Endpoint:** `GET /bharatlytics/v1/visits/analytics/host?companyId=...`

**Response:**
```json
[
    { "_id": "hostEmployeeId", "count": 10 },
    ...
]
```

#### 6. Analytics: Visits per Area
Get the number of visits per access area.

**Endpoint:** `GET /bharatlytics/v1/visits/analytics/area?companyId=...`

**Response:**
```json
[
    { "_id": "areaName", "count": 5 },
    ...
]
```

#### 7. Get Visitors
Retrieve list of visitors.

**Endpoint:** `GET /bharatlytics/v1/visitors`

**Query Parameters:**
- `companyId` (required, string): Company identifier

**Response:**
```json
{
    "visitors": [
        {
            "visitorId": "string",
            "companyId": "string",
            "visitorName": "string",
            "visitorType": "string",
            "idType": "string",
            "idNumber": "string",
            "phone": "string",
            "email": "string",
            "organization": "string",
            "status": "string",
            "blacklisted": boolean,
            "visitorImages": {
                "face": "string"
            },
            "visitorDocuments": {
                "driving_license": "string",
                "aadhar_card": "string",
                "pan_card": "string",
                "passport": "string"
            },
            "visitorEmbeddings": {
                "buffalo_l": {
                    "status": "string",
                    "embeddingId": "string"
                }
            },
            "createdAt": "string",
            "lastUpdated": "string"
        }
    ]
}
```

#### 8. Get Visits
Retrieve list of visits.

**Endpoint:** `GET /bharatlytics/v1/visits`

**Query Parameters:**
- `companyId` (optional, string): Company identifier
- `visitorId` (optional, string): Visitor identifier
- `status` (optional, string): Visit status

**Response:**
```json
{
    "visits": [
        {
            "visitId": "string",
            "visitorId": "string",
            "companyId": "string",
            "hostEmployeeId": "string",
            "purpose": "string",
            "status": "string",
            "expectedArrival": "string",
            "expectedDeparture": "string",
            "actualArrival": "string",
            "actualDeparture": "string",
            "checkInMethod": "string",
            "checkOutMethod": "string",
            "qrCode": "string",
            "createdAt": "string",
            "lastUpdated": "string"
        }
    ]
}
```

#### 9. Get Visit QR Code
Retrieve QR code for a visit.

**Endpoint:** `GET /bharatlytics/v1/visits/qr/{visitId}`

**Response:**
- Content-Type: `image/png`
- Returns QR code image

#### 10. Cleanup Duplicates
Clean up duplicate visitor records.

**Endpoint:** `POST /bharatlytics/v1/visitors/cleanup-duplicates`

**Request Format:**
- Content-Type: `multipart/form-data`

**Required Fields:**
- `companyId` (string): Company identifier

**Optional Fields:**
- `hours` (integer, min: 1, max: 168, default: 24): Hours threshold for cleanup

**Response:**
```json
{
    "message": "Successfully cleaned up X duplicate visitors",
    "deleted_count": 0,
    "hours_threshold": 24,
    "companyId": "string"
}
```

#### 11. Get Visitor Embeddings
Retrieve visitor's embedding data.

**Endpoint:** `GET /bharatlytics/v1/visitors/{visitorId}/embeddings`

**Query Parameters:**
- `companyId` (required, string): Company identifier

**Response:**
```json
{
    "visitorId": "string",
    "companyId": "string",
    "embeddings": {
        "buffalo_l": {
            "status": "string",
            "embeddingId": "string",
            "createdAt": "string",
            "updatedAt": "string",
            "finishedAt": "string"
        }
    }
}
```

### End-to-End Flow

1. **Visitor Registration**
   - Client submits visitor details and three face images (left, right, center)
   - System validates input data and images
   - Face images are stored in GridFS
   - Embedding job is queued for facial recognition
   - System checks for duplicate faces
   - Registration is marked as complete or pending based on embedding status
   - System returns MongoDB ObjectId as visitor identifier

2. **Visit Scheduling**
   - Host employee schedules visit for a registered visitor or group of visitors
   - System validates for overlapping visits (no two visits for the same visitor can overlap in time)
   - System generates a unique QR code for this specific visit
   - **QR code encodes:**
     - `visitId`
     - `expectedArrival` and `expectedDeparture` (valid time range)
     - `accessAreas` (allowed areas for this visit)
   - QR code is stored in GridFS
   - Visit record is created with scheduled status
   - QR code is made available for check-in

3. **Check-in Process**
   - Visitor arrives at premises
   - System verifies visitor identity using:
     - QR code scan (QR code is only valid within the visit's time range and for the specified access areas)
     - Facial recognition
     - Manual verification
   - Visit status is updated to checked-in
   - Actual arrival time is recorded

4. **Check-out Process**
   - Visitor completes visit
   - System verifies visitor identity
   - Visit status is updated to checked-out
   - Actual departure time is recorded

5. **Duplicate Management**
   - System detects duplicate registrations
   - Duplicate records are marked for removal
   - Cleanup process removes old duplicates
   - New registrations are prevented for duplicates

### QR Code Security and Usage
- The QR code for each visit encodes the `visitId`, the valid time window (`expectedArrival` to `expectedDeparture`), and the allowed `accessAreas`.
- The QR code is only valid for check-in during the scheduled time window and for the specified areas.
- Attempted use outside the valid time or area will be rejected by the system.

### Notes
- All timestamps are in UTC
- QR codes are generated per visit, not per visitor
- QR code content: `{ visitId, validFrom, validTo, accessAreas }`
- Visit scheduling requires valid visitor registration

### Security Considerations

1. **Authentication**
   - All endpoints require X-Auth-Token
   - Token validation for sensitive operations
   - Role-based access control

2. **Data Protection**
   - Secure storage of ID documents
   - Encrypted transmission of sensitive data
   - Access logging for audit trails

3. **Rate Limiting**
   - Request throttling per IP
   - Company-level rate limits
   - Abuse detection and prevention

4. **Input Validation**
   - Strict format validation for IDs
   - Image format and size checks
   - Email and phone number validation

### Best Practices

1. **Image Handling**
   - Use JPEG format for all images
   - Maintain aspect ratio
   - Ensure good lighting
   - Use consistent background

2. **Document Management**
   - Store documents securely
   - Validate document formats
   - Implement document retention policies

3. **Error Handling**
   - Use appropriate status codes
   - Provide clear error messages
   - Log errors for debugging
   - Implement retry mechanisms

4. **Performance**
   - Use efficient image compression
   - Implement caching where appropriate
   - Optimize database queries
   - Handle large file uploads efficiently

### Notes

1. All timestamps are in UTC
2. Image files must be in JPEG format
3. Maximum file size is 5MB per image
4. Maximum request size is 10MB
5. Embedding generation is asynchronous
6. QR codes are generated per visit, not per visitor
7. Duplicate detection uses facial recognition
8. All IDs are MongoDB ObjectIds
9. Document validation follows government standards
10. Visit scheduling requires valid visitor registration

## Entity Hierarchy Management API

The Entity Hierarchy Management API provides a flexible and dynamic way to manage hierarchical structures within your organization. This system integrates deeply with the existing employee and company management systems.

### Key Features
- Dynamic and flexible hierarchy with unlimited depth
- Custom entity types defined by customer needs
- Pre-built templates for quick setup
- Deep integration with employee and company systems
- Efficient tree traversal and management
- Asset binding to any level of hierarchy

### Base URL
All endpoints are prefixed with `/bharatlytics/v1`

### API Endpoints

#### 1. Get Entity Templates
Get available entity hierarchy templates for seeding.

**Endpoint:** `GET /entities/templates`

**Response:**
```json
{
    "manufacturing": {
        "name": "Manufacturing Template",
        "description": "Standard manufacturing hierarchy",
        "structure": {
            "type": "company",
            "children": [
                {
                    "type": "business_unit",
                    "children": [
                        {
                            "type": "plant",
                            "children": [
                                {
                                    "type": "department",
                                    "children": [
                                        {
                                            "type": "line",
                                            "children": [
                                                {"type": "workstation"}
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    },
    "office": {
        "name": "Office Template",
        "description": "Standard office hierarchy",
        "structure": {
            "type": "company",
            "children": [
                {
                    "type": "department",
                    "children": [
                        {
                            "type": "team",
                            "children": [
                                {"type": "sub_team"}
                            ]
                        }
                    ]
                }
            ]
        }
    }
}
```

#### 2. Seed Entity Hierarchy from Template
Create a complete entity hierarchy from a template.

**Endpoint:** `POST /entities/template/{template_id}`

**Path Parameters:**
- `template_id` (string): ID of the template ("manufacturing" or "office")

**Request Body:**
```json
{
    "companyId": "ObjectId"  // MongoDB ObjectId of the company
}
```

**Response:**
```json
{
    "message": "Successfully created manufacturing hierarchy",
    "created_entities": {
        "Production": "ObjectId",  // MongoDB ObjectId of created business unit
        "Quality": "ObjectId",
        "Maintenance": "ObjectId"
        // ... IDs of other created entities
    }
}
```

**Manufacturing Template Structure:**
- Business Units:
  - Production, Quality, Maintenance
- Departments under each BU:
  - Assembly, Testing, Packaging
- Lines under each Department:
  - Line A, Line B, Line C
- Workstations under each Line:
  - Station 1, Station 2, Station 3

**Office Template Structure:**
- Departments:
  - HR, Finance, IT
- Teams under each Department:
  - Recruitment, Payroll, Infrastructure
- Sub-teams under each Team:
  - Hiring, Benefits, Support

#### 3. Create Entity
Create a new entity in the hierarchy.

**Endpoint:** `POST /entities`

**Request Format:**
```json
{
    "name": "Manufacturing Plant A",
    "type": "plant",  // Any customer-defined type
    "parentId": "ObjectId",  // Optional, MongoDB ObjectId of parent entity
    "companyId": "ObjectId",  // Required, MongoDB ObjectId from company collection
    "metadata": {
        "location": "Mumbai",
        "capacity": 1000,
        "custom_field": "value"
    },
    "tags": ["critical", "manufacturing"]
}
```

**Required Fields:**
- `name` (string, max length: 100): Name of the entity
- `type` (string): Type of entity (customer-defined)
- `companyId` (ObjectId): MongoDB ObjectId from company collection

**Response:**
```json
{
    "id": "ObjectId",  // MongoDB ObjectId of created entity
    "message": "Entity created successfully"
}
```

#### 4. Link Employee to Entity
Link an existing employee to an entity node.

**Endpoint:** `POST /entities/{entity_id}/employees`

**Path Parameters:**
- `entity_id` (ObjectId): MongoDB ObjectId of the entity

**Request Body:**
```json
{
    "employeeId": "string"  // Employee ID from employee collection
}
```

**Response:**
```json
{
    "message": "Employee linked to entity",
    "entityId": "ObjectId",
    "employeeId": "string"
}
```

**Notes:**
- Creates/updates an asset of type 'employee'
- Maintains reference to employee document
- Handles employee reassignment between entities
- Ensures company-level scoping

#### 5. Get Entity Details
Get details of a specific entity.

**Endpoint:** `GET /entities/{entity_id}`

**Response:**
```json
{
    "_id": "ObjectId",
    "name": "string",
    "type": "string",
    "parentId": "ObjectId",
    "companyId": "ObjectId",
    "path": ["ObjectId"],  // Array of ancestor ObjectIds
    "metadata": {},
    "tags": [],
    "createdAt": "string",
    "updatedAt": "string"
}
```

#### 6. Get Entity Children
Get direct children of an entity.

**Endpoint:** `GET /entities/{entity_id}/children`

**Query Parameters:**
- `type` (optional): Filter children by type

**Response:**
```json
[
    {
        "_id": "ObjectId",
        "name": "string",
        "type": "string",
        "parentId": "ObjectId",
        "companyId": "ObjectId",
        "path": ["ObjectId"],
        "metadata": {},
        "tags": []
    }
]
```

#### 7. Get Entity Assets
Get all assets under an entity (including descendants).

**Endpoint:** `GET /entities/{entity_id}/assets`

**Query Parameters:**
- `type` (optional): Filter by asset type
- `include_employee_details` (optional, boolean): Include employee details for employee assets

**Response:**
```json
[
    {
        "_id": "ObjectId",
        "name": "string",
        "type": "string",
        "entityId": "ObjectId",
        "companyId": "ObjectId",
        "metadata": {
            "employeeId": "string",  // For employee assets
            "employeeRef": "ObjectId",  // Reference to employee collection
            "designation": "string",
            "email": "string",
            "mobile": "string"
        },
        "employeeDetails": {  // Only if include_employee_details=true
            "_id": "ObjectId",
            "employeeId": "string",
            "employeeName": "string",
            // ... other employee fields
        }
    }
]
```

### Best Practices

1. **Entity Types**
   - Use consistent type naming within your organization
   - Document your type hierarchy
   - Consider using templates for standard structures

2. **Employee Integration**
   - Link employees to the most specific entity in hierarchy
   - Use employee assets for role-based access control
   - Keep employee references updated

3. **Template Usage**
   - Start with a template for standard hierarchies
   - Customize after seeding
   - Document custom entity types

4. **Performance**
   - Use children API for direct children
   - Use descendants API sparingly
   - Index important metadata fields

### Security Notes

1. **Access Control**
   - Entity access is controlled by company scope
   - Employee access inherits company permissions
   - Validate company access for all operations

2. **Data Validation**
   - Entity names are validated (max 100 chars)
   - Types must be non-empty strings
   - Company IDs must be valid ObjectIds

### Notes

1. All IDs are MongoDB ObjectIds unless specified
2. Company scope is enforced at all levels
3. Employee-entity links are managed through assets
4. Templates are customizable after seeding
5. Metadata size limit: 16KB
6. Maximum children per node: 1000
7. Maximum hierarchy depth: 50 levels
8. All timestamps are in UTC 

# Bharatlytics Entity Hierarchy Management API Documentation

## Overview
The Entity Hierarchy Management system allows companies to create and manage organizational hierarchies (like manufacturing plants, office structures, etc.) and link employees to different levels of these hierarchies.

## Base URL
All endpoints are prefixed with `/bharatlytics/v1`

## Authentication
All endpoints require authentication. Include the authentication token in the request header:
```
Authorization: Bearer <your_token>
```

## Entity Templates

### 1. Get All Templates
**GET** `/entities/templates`

Returns all active entity templates.

**Response**
```json
[
    {
        "_id": "template_id",
        "name": "Manufacturing Hierarchy",
        "description": "Standard manufacturing facility hierarchy",
        "type": "manufacturing",
        "structure": {
            "business_units": ["Production", "Quality", "Maintenance"],
            "departments": ["Assembly", "Testing", "Packaging"],
            "lines": ["Line A", "Line B", "Line C"],
            "workstations": ["Station 1", "Station 2", "Station 3"]
        },
        "metadata": {
            "industry": "Manufacturing",
            "recommended_for": ["Factories", "Plants", "Production Facilities"]
        },
        "status": "active",
        "version": "1.0"
    }
]
```

### 2. Create Template
**POST** `/entities/templates`

Create a new entity template.

**Request Body**
```json
{
    "name": "Custom Manufacturing",
    "description": "Custom manufacturing template",
    "type": "manufacturing",
    "structure": {
        "plants": ["Plant 1", "Plant 2"],
        "departments": ["Production", "QA"],
        "lines": ["Assembly", "Packaging"]
    },
    "metadata": {
        "industry": "Manufacturing",
        "customizable": true
    }
}
```

**Response**
```json
{
    "id": "template_id",
    "message": "Template created successfully"
}
```

### 3. Clone Template
**POST** `/entities/templates/{template_id}/clone`

Clone a template to create a company-specific hierarchy.

**Request Body**
```json
{
    "companyId": "company_id",
    "namePrefix": "Mumbai-"  // Optional
}
```

**Response**
```json
{
    "message": "Successfully cloned template hierarchy",
    "created_entities": {
        "entity_id1": {
            "name": "Mumbai-Plant 1",
            "type": "plant",
            "children": {
                "entity_id2": {
                    "name": "Mumbai-Production",
                    "type": "department",
                    "children": {}
                }
            }
        }
    }
}
```

## Entity Management

### 1. Create Entity
**POST** `/entities`

Create a new entity in the hierarchy.

**Request Body**
```json
{
    "name": "Assembly Line 1",
    "type": "line",
    "companyId": "company_id",
    "parentId": "department_entity_id",  // Optional
    "metadata": {
        "capacity": "1000 units/day",
        "shift_count": 3
    },
    "tags": ["high-capacity", "automated"]
}
```

**Response**
```json
{
    "id": "entity_id",
    "message": "Entity created successfully"
}
```

### 2. Get Entity
**GET** `/entities/{entity_id}`

Get entity details.

**Response**
```json
{
    "_id": "entity_id",
    "name": "Assembly Line 1",
    "type": "line",
    "parentId": "department_entity_id",
    "path": ["root_id", "plant_id", "department_id"],
    "companyId": "company_id",
    "metadata": {
        "capacity": "1000 units/day",
        "shift_count": 3
    },
    "tags": ["high-capacity", "automated"]
}
```

### 3. Delete Entity
**DELETE** `/entities/{entity_id}`

Deletes an entity and all its descendants. Also removes all asset links.

**Response**
```json
{
    "success": true
}
```

## Employee-Entity Linking

### 1. Link Employee to Entity
**POST** `/entities/{entity_id}/employees`

Link an existing employee to an entity in the hierarchy.

**Request Body**
```json
{
    "employeeId": "EMP001"
}
```

**Response**
```json
{
    "message": "Employee linked to entity",
    "entityId": "entity_id",
    "employeeId": "EMP001"
}
```

### 2. Get Entity Assets (Including Employees)
**GET** `/entities/{entity_id}/assets?type=employee&include_employee_details=true`

Get all employees linked to an entity and its descendants.

**Response**
```json
[
    {
        "_id": "asset_id",
        "name": "John Doe",
        "type": "employee",
        "entityId": "entity_id",
        "orgId": "org_id",
        "metadata": {
            "employeeId": "EMP001",
            "employeeRef": "employee_doc_id",
            "designation": "Line Supervisor",
            "email": "john@company.com",
            "mobile": "+1234567890"
        },
        "employeeDetails": {
            "_id": "employee_doc_id",
            "employeeId": "EMP001",
            "employeeName": "John Doe",
            "companyId": "company_id",
            "employeeDesignation": "Line Supervisor",
            "employeeEmail": "john@company.com",
            "employeeMobile": "+1234567890",
            "status": "active"
        }
    }
]
```

## Workflow Examples

### 1. Creating a Manufacturing Hierarchy and Linking Employees

1. **Clone a Manufacturing Template**
```json
POST /bharatlytics/v1/entities/templates/{template_id}/clone
{
    "companyId": "company_id",
    "namePrefix": "Mumbai-"
}
```

2. **Link Department Head**
```json
POST /bharatlytics/v1/entities/{department_id}/employees
{
    "employeeId": "EMP001"  // Department Head
}
```

3. **Link Line Supervisor**
```json
POST /bharatlytics/v1/entities/{line_id}/employees
{
    "employeeId": "EMP002"  // Line Supervisor
}
```

4. **Link Workstation Operators**
```json
POST /bharatlytics/v1/entities/{workstation_id}/employees
{
    "employeeId": "EMP003"  // Operator
}
```

### 2. Moving Employees Between Entities

1. **Move Employee to New Entity**
```json
POST /bharatlytics/v1/entities/{new_entity_id}/employees
{
    "employeeId": "EMP001"
}
```
The system will automatically handle:
- Removing the old entity link
- Creating the new entity link
- Updating all relevant metadata

## Notes

1. **Employee Linking Rules**:
   - An employee can only be linked to one entity at a time
   - When linking to a new entity, any existing link is automatically removed
   - Links are company-scoped for security

2. **Hierarchy Navigation**:
   - Use the `path` array to traverse up the hierarchy
   - Use `/entities/{entity_id}/children` to get immediate children
   - Use `/entities/{entity_id}/descendants` to get all descendants

3. **Best Practices**:
   - Link managers/supervisors to their respective department/line entities
   - Link operators to specific workstation entities
   - Use metadata to store role-specific information
   - Use tags for easy filtering and searching

### Security Notes

1. **Access Control**
   - Entity access is controlled by company scope
   - Employee access inherits company permissions
   - Validate company access for all operations

2. **Data Validation**
   - Entity names are validated (max 100 chars)
   - Types must be non-empty strings
   - Company IDs must be valid ObjectIds

### Notes

1. All IDs are MongoDB ObjectIds unless specified
2. Company scope is enforced at all levels
3. Employee-entity links are managed through assets
4. Templates are customizable after seeding
5. Metadata size limit: 16KB
6. Maximum children per node: 1000
7. Maximum hierarchy depth: 50 levels
8. All timestamps are in UTC 