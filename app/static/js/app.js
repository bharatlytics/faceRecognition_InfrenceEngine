// Global state
const state = {
    currentCompany: null,
    currentEntity: null,
    entities: [],
    companies: [],
    entityDefinitions: []
};

// API Configuration
const API_BASE_URL = '/bharatlytics/v1';

// Utility Functions
function showSpinner() {
    const spinner = $('<div class="spinner-overlay"><div class="spinner-border text-primary"></div></div>');
    $('body').append(spinner);
}

function hideSpinner() {
    $('.spinner-overlay').remove();
}

function showToast(message, type = 'success') {
    const toast = $(`
        <div class="toast" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="toast-header bg-${type} text-white">
                <strong class="me-auto">Notification</strong>
                <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
            </div>
            <div class="toast-body">${message}</div>
        </div>
    `);
    
    $('.toast-container').append(toast);
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    toast.on('hidden.bs.toast', () => toast.remove());
}

// Navigation
$(document).on('click', '.nav-link', function(e) {
    e.preventDefault();
    const page = $(this).data('page');
    $('.nav-link').removeClass('active');
    $(this).addClass('active');
    $('.page').removeClass('active');
    $(`#${page}-page`).addClass('active');
    
    if (page === 'companies') {
        loadCompanies();
    } else if (page === 'entities' && state.currentCompany) {
        loadEntities();
    }
});

// Companies Management
function loadCompanies() {
    showSpinner();
    $.get(`${API_BASE_URL}/companies`)
        .done(response => {
            console.log('Companies loaded:', response); // Debug log
            state.companies = response.companies || [];
            renderCompanies();
        })
        .fail(error => {
            console.error('Error loading companies:', error); // Debug log
            showToast('Failed to load companies', 'danger');
        })
        .always(() => hideSpinner());
}

function renderCompanies() {
    const container = $('#app');
    container.empty();
    
    const companiesContainer = $('<div class="container-fluid mt-4"></div>');
    
    // Add buttons container
    const buttonsContainer = $('<div class="mb-4 d-flex gap-2"></div>');
    
    // Add "Add Company" button
    const addButton = $(`
        <button class="btn btn-primary" id="add-company-btn">
            <i class="fas fa-plus"></i> Add Company
        </button>
    `);
    
    buttonsContainer.append(addButton);
    
    // Add "Seed Company" button if no companies exist
    if (state.companies.length === 0) {
        const seedButton = $(`
            <button class="btn btn-secondary" id="seed-company-btn">
                <i class="fas fa-seedling"></i> Seed Demo Company
            </button>
        `);
        buttonsContainer.append(seedButton);
    }
    
    companiesContainer.append(buttonsContainer);
    
    // Create table
    const table = $(`
        <table class="table table-striped table-hover">
            <thead>
                <tr>
                    <th>Company ID</th>
                    <th>Company Name</th>
                    <th>Industry</th>
                    <th>Email</th>
                    <th>Phone</th>
                    <th>Website</th>
                    <th>Designations</th>
                    <th>Created At</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody></tbody>
        </table>
    `);
    
    if (state.companies.length === 0) {
        companiesContainer.append('<div class="alert alert-info">No companies found. Add a company to get started or use the seed button to create a demo company.</div>');
    } else {
        state.companies.forEach(company => {
            const row = $(
                `<tr>
                    <td><small class="text-muted">${company._id}</small></td>
                    <td>
                        <div style="color: ${company.colorScheme?.primary || '#000'}">
                            ${company.companyName}
                        </div>
                    </td>
                    <td>${company.industry || '-'}</td>
                    <td>${company.email || '-'}</td>
                    <td>${company.phone || '-'}</td>
                    <td>${company.website ? `<a href="${company.website}" target="_blank">${company.website}</a>` : '-'}</td>
                    <td>${company.designations ? `<span class="badge bg-secondary">${company.designations.length}</span>` : '0'}</td>
                    <td>${new Date(company.createdAt).toLocaleDateString()}</td>
                    <td>
                        <div class="btn-group">
                            <button class="btn btn-sm btn-primary edit-company" data-company-id="${company._id}" title="Edit Company">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button class="btn btn-sm btn-success manage-entities" data-company-id="${company._id}" title="Manage Entities">
                                <i class="fas fa-sitemap"></i>
                            </button>
                            <button class="btn btn-sm btn-danger delete-company" data-company-id="${company._id}" title="Delete Company">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </td>
                </tr>`
            );
            table.find('tbody').append(row);
        });
        
        companiesContainer.append(table);
    }
    
    container.append(companiesContainer);
}

// Company Modal Management
$(document).on('click', '#add-company-btn', function() {
    $('#company-form')[0].reset();
    $('#company-form [name="_id"]').val('');
    $('#company-modal').modal('show');
});

// Company Form Handling
$(document).on('click', '#save-company-btn', function() {
    const form = $('#company-form');
    if (!form[0].checkValidity()) {
        form[0].reportValidity();
        return;
    }
    
    const formData = new FormData(form[0]);
    const company = {
        companyName: formData.get('companyName'),
        address: formData.get('address'),
        phone: formData.get('phone'),
        email: formData.get('email'),
        website: formData.get('website'),
        industry: formData.get('industry'),
        designations: formData.get('designations').split(',').map(d => d.trim()).filter(d => d),
        colorScheme: {
            primary: formData.get('colorScheme.primary'),
            secondary: formData.get('colorScheme.secondary'),
            accent: formData.get('colorScheme.accent')
        }
    };
    
    const companyId = formData.get('_id');
    const method = companyId ? 'PATCH' : 'POST';
    const url = companyId ? 
        `${API_BASE_URL}/companies/${companyId}` : 
        `${API_BASE_URL}/companies`;
    
    showSpinner();
    $.ajax({
        url: url,
        method: method,
        data: JSON.stringify(company),
        contentType: 'application/json'
    })
        .done(() => {
            $('#company-modal').modal('hide');
            showToast(`Company ${companyId ? 'updated' : 'created'} successfully`);
            loadCompanies();
        })
        .fail(() => showToast('Failed to save company', 'danger'))
        .always(() => hideSpinner());
});

// Entity Management
function loadEntities(companyId) {
    state.currentCompany = companyId;
    showSpinner();
    
    $.get(`${API_BASE_URL}/entities?companyId=${companyId}`)
        .done(response => {
            console.log('Entities loaded:', response);
            state.entities = response.entities || [];
            renderEntities();
        })
        .fail(error => {
            console.error('Error loading entities:', error);
            showToast('Failed to load entities', 'danger');
        })
        .always(() => hideSpinner());
}

function renderEntities() {
    const container = $('#app');
    container.empty();
    
    const entitiesContainer = $('<div class="container-fluid mt-4"></div>');
    
    // Add navigation breadcrumb
    const breadcrumb = $(`
        <nav aria-label="breadcrumb">
            <ol class="breadcrumb">
                <li class="breadcrumb-item"><a href="#" class="back-to-companies">Companies</a></li>
                <li class="breadcrumb-item active">Entity Management</li>
            </ol>
        </nav>
    `);
    entitiesContainer.append(breadcrumb);
    
    // Add buttons container
    const buttonsContainer = $('<div class="mb-4 d-flex gap-2"></div>');
    
    // Add "Add Entity" button
    const addButton = $(`
        <button class="btn btn-primary" id="add-entity-btn">
            <i class="fas fa-plus"></i> Add Entity
        </button>
    `);
    
    // Add "Manage Definitions" button
    const definitionsButton = $(`
        <button class="btn btn-secondary" id="manage-definitions-btn">
            <i class="fas fa-cog"></i> Manage Definitions
        </button>
    `);
    
    buttonsContainer.append(addButton, definitionsButton);
    entitiesContainer.append(buttonsContainer);
    
    // Create entity tree view
    const treeContainer = $('<div class="entity-tree mt-4"></div>');
    renderEntityTree(null, treeContainer);
    entitiesContainer.append(treeContainer);
    
    container.append(entitiesContainer);
}

function renderEntityTree(parentId = null, container = null) {
    const treeContainer = container || $('#entity-tree');
    if (!parentId) treeContainer.empty();
    
    const entities = state.entities.filter(e => 
        (parentId === null && !e.parentId) || 
        (e.parentId === parentId)
    );
    
    if (entities.length === 0 && !parentId) {
        treeContainer.html('<p class="text-muted">No entities found</p>');
        return;
    }
    
    const list = $('<ul class="list-unstyled mb-0"></ul>');
    
    entities.forEach(entity => {
        const item = $(`
            <li class="mb-2">
                <div class="entity-tree-item" data-entity-id="${entity._id}">
                    <div class="d-flex align-items-center">
                        <i class="fas fa-${getEntityIcon(entity.type)} text-${getTypeColor(entity.type)} me-2"></i>
                        <div>
                            <div class="fw-bold">${entity.name}</div>
                            <div class="small text-muted">
                                <span class="badge bg-secondary me-1">${entity.type}</span>
                                ${Object.entries(entity.attributes || {})
                                    .map(([key, value]) => `<span class="badge bg-light text-dark">${key}: ${value}</span>`)
                                    .join(' ')}
                            </div>
                        </div>
                        <div class="ms-auto">
                            <button class="btn btn-sm btn-outline-primary edit-entity" data-entity-id="${entity._id}">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-danger delete-entity" data-entity-id="${entity._id}">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
                <div class="entity-children ms-4"></div>
            </li>
        `);
        
        list.append(item);
        renderEntityTree(entity._id, item.find('.entity-children'));
    });
    
    treeContainer.append(list);
}

function getEntityIcon(type) {
    const icons = {
        company: 'building',
        business_unit: 'briefcase',
        plant: 'industry',
        department: 'layer-group',
        line: 'stream',
        workstation: 'desktop',
        team: 'users',
        sub_team: 'user-friends',
        office: 'building-user',
        floor: 'stairs',
        zone: 'map-marker-alt',
        area: 'square',
        machine: 'cog',
        device: 'microchip',
        sensor: 'wave-square'
    };
    return icons[type] || 'circle';
}

function getTypeColor(type) {
    const colors = {
        company: 'primary',
        business_unit: 'info',
        plant: 'success',
        department: 'warning',
        line: 'danger',
        workstation: 'secondary',
        team: 'info',
        sub_team: 'secondary',
        office: 'primary',
        floor: 'warning',
        zone: 'danger',
        area: 'success',
        machine: 'info',
        device: 'warning',
        sensor: 'secondary'
    };
    return colors[type] || 'secondary';
}

// Entity Modal Management
$(document).on('click', '#add-entity-btn', function() {
    // First check if we have any entity definitions
    if (state.entityDefinitions.length === 0) {
        showToast('Please create an entity definition first', 'warning');
        return;
    }
    
    $('#entity-form')[0].reset();
    $('#entity-form [name="_id"]').val('');
    
    // Populate definition select
    const definitionSelect = $('#entity-form [name="definitionId"]');
    definitionSelect.empty().append('<option value="">Select Definition</option>');
    state.entityDefinitions.forEach(def => {
        definitionSelect.append(`<option value="${def._id}">${def.name}</option>`);
    });
    
    $('#entity-modal').modal('show');
});

$(document).on('change', '#entity-form [name="definitionId"]', function() {
    const definitionId = $(this).val();
    if (!definitionId) return;
    
    const definition = state.entityDefinitions.find(d => d._id === definitionId);
    if (!definition) return;
    
    // Populate type select based on definition
    const typeSelect = $('#entity-form [name="type"]');
    typeSelect.empty().append('<option value="">Select Type</option>');
    Object.keys(definition.structure.entityTypes).forEach(type => {
        typeSelect.append(`<option value="${type}">${definition.structure.entityTypes[type].description || type}</option>`);
    });
});

$(document).on('change', '#entity-form [name="type"]', function() {
    const definitionId = $('#entity-form [name="definitionId"]').val();
    const type = $(this).val();
    if (!definitionId || !type) return;
    
    const definition = state.entityDefinitions.find(d => d._id === definitionId);
    if (!definition) return;
    
    // Populate parent select based on allowed relationships
    const parentSelect = $('#entity-form [name="parentId"]');
    parentSelect.empty().append('<option value="">No Parent</option>');
    
    const allowedParentTypes = definition.relationships
        .filter(rel => rel.childType === type)
        .map(rel => rel.parentType);
    
    if (allowedParentTypes.length > 0) {
        state.entities
            .filter(e => allowedParentTypes.includes(e.type))
            .forEach(e => {
                parentSelect.append(`<option value="${e._id}">${e.name} (${e.type})</option>`);
            });
    }
    
    // Show/hide attribute fields based on definition
    const attrContainer = $('#entity-attributes');
    attrContainer.empty();
    
    const allowedAttrs = definition.structure.allowedAttributes[type] || [];
    allowedAttrs.forEach(attr => {
        const required = definition.structure.entityTypes[type]?.requiredAttributes?.includes(attr);
        const allowedValues = definition.structure.entityTypes[type]?.allowedValues?.[attr];
        
        if (allowedValues) {
            // Create select for enum values
            attrContainer.append(`
                <div class="mb-3">
                    <label class="form-label">${attr}</label>
                    <select class="form-control" name="attributes.${attr}" ${required ? 'required' : ''}>
                        <option value="">Select ${attr}</option>
                        ${allowedValues.map(v => `<option value="${v}">${v}</option>`).join('')}
                    </select>
                </div>
            `);
        } else {
            // Create text input for free-form values
            attrContainer.append(`
                <div class="mb-3">
                    <label class="form-label">${attr}</label>
                    <input type="text" class="form-control" name="attributes.${attr}" ${required ? 'required' : ''}>
                </div>
            `);
        }
    });
});

$(document).on('click', '#manage-definitions-btn', function() {
    loadEntityDefinitions();
});

// Edit company handler
$(document).on('click', '.edit-company', function(e) {
    e.stopPropagation();
    const companyId = $(this).data('company-id');
    const company = state.companies.find(c => c._id === companyId);
    
    if (company) {
        const form = $('#company-form')[0];
        form.elements['_id'].value = company._id;
        form.elements['companyName'].value = company.companyName;
        form.elements['address'].value = company.address || '';
        form.elements['phone'].value = company.phone || '';
        form.elements['email'].value = company.email || '';
        form.elements['website'].value = company.website || '';
        form.elements['industry'].value = company.industry || '';
        form.elements['designations'].value = (company.designations || []).join(', ');
        
        if (company.colorScheme) {
            form.elements['colorScheme.primary'].value = company.colorScheme.primary || '#000000';
            form.elements['colorScheme.secondary'].value = company.colorScheme.secondary || '#ffffff';
            form.elements['colorScheme.accent'].value = company.colorScheme.accent || '#cccccc';
        }
        
        $('#company-modal').modal('show');
    }
});

// Delete company handler
$(document).on('click', '.delete-company', function(e) {
    e.stopPropagation();
    const companyId = $(this).data('company-id');
    
    if (confirm('Are you sure you want to delete this company? This will also delete all associated entities.')) {
        showSpinner();
        $.ajax({
            url: `${API_BASE_URL}/companies/${companyId}`,
            method: 'DELETE'
        })
            .done(() => {
                showToast('Company deleted successfully');
                loadCompanies();
            })
            .fail(() => showToast('Failed to delete company', 'danger'))
            .always(() => hideSpinner());
    }
});

// Manage entities handler
$(document).on('click', '.manage-entities', function() {
    const companyId = $(this).data('company-id');
    state.currentCompany = companyId;
    loadEntities(companyId);
});

$(document).on('click', '.entity-tree-item', function() {
    const entityId = $(this).data('entity-id');
    const entity = state.entities.find(e => e._id === entityId);
    
    if (entity) {
        $('.entity-tree-item').removeClass('active');
        $(this).addClass('active');
        renderEntityDetails(entity);
    }
});

function renderEntityDetails(entity) {
    const details = $('#entity-details');
    details.html(`
        <div class="entity-detail-row">
            <div class="entity-detail-label">Name</div>
            <div>${entity.name}</div>
        </div>
        <div class="entity-detail-row">
            <div class="entity-detail-label">Type</div>
            <div><span class="badge bg-secondary">${entity.type}</span></div>
        </div>
        <div class="entity-detail-row">
            <div class="entity-detail-label">Tags</div>
            <div>${entity.tags.map(t => `<span class="badge bg-info me-1">${t}</span>`).join('')}</div>
        </div>
        <div class="entity-detail-row">
            <div class="entity-detail-label">Metadata</div>
            <pre><code>${JSON.stringify(entity.metadata, null, 2)}</code></pre>
        </div>
        <div class="mt-3">
            <button class="btn btn-danger delete-entity" data-entity-id="${entity._id}">
                <i class="fas fa-trash"></i> Delete
            </button>
        </div>
    `);
}

$(document).on('click', '.delete-entity', function() {
    const entityId = $(this).data('entity-id');
    
    if (confirm('Are you sure you want to delete this entity and all its descendants?')) {
        showSpinner();
        $.ajax({
            url: `${API_BASE_URL}/entities/${entityId}`,
            method: 'DELETE'
        })
            .done(() => {
                showToast('Entity deleted successfully');
                loadEntities();
            })
            .fail(() => showToast('Failed to delete entity', 'danger'))
            .always(() => hideSpinner());
    }
});

// Add seed company handler
$(document).on('click', '#seed-company-btn', function() {
    showSpinner();
    $.ajax({
        url: `${API_BASE_URL}/companies/seed`,
        method: 'POST',
        contentType: 'application/json'
    })
        .done(response => {
            showToast('Demo company created successfully');
            loadCompanies();
        })
        .fail(() => showToast('Failed to create demo company', 'danger'))
        .always(() => hideSpinner());
});

// Entity Form Handling
$(document).on('click', '#save-entity-btn', function() {
    const form = $('#entity-form');
    if (!form[0].checkValidity()) {
        form[0].reportValidity();
        return;
    }
    
    const formData = new FormData(form[0]);
    const entityId = formData.get('_id');
    
    // Build attributes object from dynamic fields
    const attributes = {};
    form.find('[name^="attributes."]').each(function() {
        const field = $(this);
        const attrName = field.attr('name').replace('attributes.', '');
        attributes[attrName] = field.val();
    });
    
    // Build entity data
    const entity = {
        name: formData.get('name'),
        type: formData.get('type'),
        definitionId: formData.get('definitionId'),
        parentId: formData.get('parentId') || null,
        companyId: state.currentCompany,
        attributes: attributes,
        tags: formData.get('tags').split(',').map(t => t.trim()).filter(t => t)
    };
    
    try {
        entity.metadata = JSON.parse(formData.get('metadata') || '{}');
    } catch (e) {
        showToast('Invalid metadata JSON', 'danger');
        return;
    }
    
    showSpinner();
    $('#entity-modal').modal('hide');
    
    $.ajax({
        url: entityId ? 
            `${API_BASE_URL}/entities/${entityId}` : 
            `${API_BASE_URL}/entities`,
        method: entityId ? 'PUT' : 'POST',
        data: JSON.stringify(entity),
        contentType: 'application/json'
    })
        .done(() => {
            showToast(`Entity ${entityId ? 'updated' : 'created'} successfully`);
            loadEntities(state.currentCompany);
        })
        .fail(error => {
            console.error('Failed to save entity:', error);
            showToast(error.responseJSON?.error || 'Failed to save entity', 'danger');
        })
        .always(() => hideSpinner());
});

// Add edit entity handler
$(document).on('click', '.edit-entity', function(e) {
    e.preventDefault();
    e.stopPropagation();
    const entityId = $(this).data('entity-id');
    const entity = state.entities.find(e => e._id === entityId);
    
    if (entity) {
        showSpinner();
        
        // First load the entity definition to set up the form
        $.get(`${API_BASE_URL}/entity-definitions/${entity.definitionId}`)
            .done(definition => {
                const form = $('#entity-form')[0];
                
                // Set basic fields
                form.elements['_id'].value = entity._id;
                form.elements['name'].value = entity.name;
                
                // Set and trigger definition select
                const definitionSelect = $(form.elements['definitionId']);
                definitionSelect.val(entity.definitionId);
                definitionSelect.trigger('change');
                
                // Set and trigger type select
                setTimeout(() => {
                    const typeSelect = $(form.elements['type']);
                    typeSelect.val(entity.type);
                    typeSelect.trigger('change');
                    
                    // Set parent after type is set (to ensure valid parents are loaded)
                    setTimeout(() => {
                        if (entity.parentId) {
                            $(form.elements['parentId']).val(entity.parentId);
                        }
                        
                        // Set attributes
                        Object.entries(entity.attributes || {}).forEach(([key, value]) => {
                            $(`[name="attributes.${key}"]`).val(value);
                        });
                        
                        // Set remaining fields
                        form.elements['tags'].value = (entity.tags || []).join(', ');
                        form.elements['metadata'].value = JSON.stringify(entity.metadata || {}, null, 2);
                        
                        $('#entity-modal').modal('show');
                    }, 100);
                }, 100);
            })
            .fail(error => {
                console.error('Failed to load entity definition:', error);
                showToast('Failed to load entity definition', 'danger');
            })
            .always(() => hideSpinner());
    }
});

// Initialize
$(document).ready(() => {
    loadCompanies();
    
    // Create toast container
    $('body').append('<div class="toast-container"></div>');
}); 