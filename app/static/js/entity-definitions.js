// Entity Definition Management

// Register Cytoscape extensions
cytoscape.use(cytoscapeDagre);
cytoscape.use(cytoscapeKlay);

// Add at the top of the file, outside any function:
let lastPaperScale = 1;
let lastPaperTranslate = { x: 0, y: 0 };
let currentPaper = null;

function savePaperState() {
    if (!currentPaper) return;
    lastPaperScale = currentPaper.scale().sx;
    lastPaperTranslate = currentPaper.translate();
}

// Initialize Cytoscape with default configuration
const initializeCytoscape = (container, elements) => {
    return cytoscape({
        container: container,
        elements: elements,
        style: [
            {
                selector: 'node',
                style: {
                    'label': 'data(label)',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'background-color': 'data(isAttribute)',
                    'background-opacity': function(ele) {
                        return ele.data('isAttribute') ? 0.2 : 1;
                    },
                    'border-width': 2,
                    'border-color': '#0d6efd',
                    'padding': '10px',
                    'width': 'label',
                    'height': 'label',
                    'shape': function(ele) {
                        return ele.data('isAttribute') ? 'ellipse' : 'rectangle';
                    },
                    'text-wrap': 'wrap',
                    'text-max-width': '120px'
                }
            },
            {
                selector: 'edge',
                style: {
                    'label': 'data(label)',
                    'curve-style': 'bezier',
                    'target-arrow-shape': 'triangle',
                    'line-color': '#6c757d',
                    'target-arrow-color': '#6c757d',
                    'text-background-color': '#ffffff',
                    'text-background-opacity': 1,
                    'text-background-padding': '5px',
                    'text-rotation': 'autorotate',
                    'arrow-scale': 0.8,
                    'width': 1.5,
                    'line-style': function(ele) {
                        return ele.data('isAttributeEdge') ? 'dashed' : 'solid';
                    }
                }
            }
        ],
        layout: {
            name: 'dagre',
            rankDir: 'TB',
            padding: 50,
            spacingFactor: 1.5,
            animate: true,
            animationDuration: 500,
            fit: true,
            nodeDimensionsIncludeLabels: true
        },
        wheelSensitivity: 0.2,
        minZoom: 0.5,
        maxZoom: 2
    });
}

function generateGraphData(definition) {
    try {
        const types = definition.structure.entityTypes || [];
        if (!Array.isArray(types) || types.length === 0) {
            return {
                nodes: [{ data: { id: 'error', label: 'No entity types defined' } }],
                edges: []
            };
        }
        const nodes = [];
        const edges = [];
        // Add entity type nodes
        types.forEach(typeObj => {
            nodes.push({
                data: {
                    id: typeObj.name,
                    label: typeObj.name,
                    description: typeObj.description || typeObj.name
                }
            });
            // Add attribute nodes and dotted edges
            (typeObj.attributes || []).forEach(attrObj => {
                const attrNodeId = `${typeObj.name}__attr__${attrObj.name}`;
                nodes.push({
                    data: {
                        id: attrNodeId,
                        label: attrObj.name,
                        isAttribute: true
                    }
                });
                edges.push({
                    data: {
                        id: `edge-${typeObj.name}-${attrObj.name}`,
                        source: typeObj.name,
                        target: attrNodeId,
                        label: '',
                        isAttributeEdge: true
                    }
                });
            });
        });
        // Add relationship edges
        (definition.relationships || []).forEach((rel, index) => {
            if (!rel.parentType || !rel.childType) return;
            const maxChildren = rel.constraints?.maxChildren || '∞';
            const minChildren = rel.constraints?.minChildren || '0';
            edges.push({
                data: {
                    id: `edge-${index}`,
                    source: rel.parentType,
                    target: rel.childType,
                    label: `${minChildren}..${maxChildren}`
                }
            });
        });
        return { nodes, edges };
    } catch (error) {
        return {
            nodes: [{ data: { id: 'error', label: 'Error generating diagram' } }],
            edges: []
        };
    }
}

function generateMetadataSchema(definition) {
    const schema = {};
    
    Object.entries(definition.structure.entityTypes).forEach(([type, info]) => {
        schema[type] = {
            required: info.requiredAttributes || [],
            properties: {}
        };
        
        const attributes = definition.structure.allowedAttributes[type] || [];
        attributes.forEach(attr => {
            schema[type].properties[attr] = {
                type: info.allowedValues?.[attr] ? 'enum' : 'string',
                allowedValues: info.allowedValues?.[attr] || []
            };
        });
    });
    
    return schema;
}

function renderDefinitionDiagram(definition) {
    ensureEntityTypesArray(definition);
    renderJointJSDiagram('definition-diagram', definition);
}

function renderMetadataSchema(definition) {
    const schema = generateMetadataSchema(definition);
    $('#metadata-schema-content').html(`
        <div class="metadata-schema">
            ${Object.entries(schema).map(([type, typeSchema]) => `
                <div class="card mb-3">
                    <div class="card-header">
                        <h6 class="mb-0">${type}</h6>
                    </div>
                    <div class="card-body">
                        <h6 class="text-muted">Required Fields</h6>
                        <p>${typeSchema.required.length ? typeSchema.required.join(', ') : 'None'}</p>
                        
                        <h6 class="text-muted">Properties</h6>
                        <table class="table table-sm">
                            <thead>
                                <tr>
                                    <th>Field</th>
                                    <th>Type</th>
                                    <th>Allowed Values</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${Object.entries(typeSchema.properties).map(([field, prop]) => `
                                    <tr>
                                        <td>${field}</td>
                                        <td>${prop.type}</td>
                                        <td>${prop.allowedValues.length ? prop.allowedValues.join(', ') : '-'}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            `).join('')}
        </div>
    `);
}

function loadEntityDefinitions() {
    showSpinner();
    $.get(`${API_BASE_URL}/entity-definitions?companyId=${state.currentCompany}`)
        .done(response => {
            state.entityDefinitions = response || [];
            renderEntityDefinitions();
        })
        .fail(error => {
            console.error('Failed to load entity definitions:', error);
            showToast('Failed to load entity definitions', 'danger');
        })
        .always(() => hideSpinner());
}

function renderEntityDefinitions() {
    const container = $('#app');
    container.empty();

    if (state.entityDefinitions.length === 0) {
        container.append('<div class="alert alert-info">No entity definitions found. Create one to get started or use a template.</div>');
        return;
    }

    // Layout: row with two columns (col-md-4 left, col-md-8 right)
    const row = $('<div class="row"></div>');
    const leftCol = $('<div class="col-md-4"></div>');
    const rightCol = $('<div class="col-md-8" id="definition-details-panel"></div>');

    // Stack cards vertically in leftCol, add hover/active cues
    state.entityDefinitions.forEach((definition, idx) => {
        const card = $(`
            <div class="card mb-3 definition-card" data-definition-id="${definition._id}" style="cursor:pointer; transition: box-shadow 0.2s;">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h5 class="card-title mb-0"><i class="fas fa-sitemap me-2 text-primary"></i>${definition.name}</h5>
                    <span class="badge bg-${definition.status === 'active' ? 'success' : 'warning'}">
                        ${definition.status}
                    </span>
                </div>
                <div class="card-body">
                    <div class="definition-preview" style="height: 120px;"></div>
                    <p class="card-text mt-2">${definition.description || ''}</p>
                </div>
            </div>
        `);
        if (idx === 0) card.addClass('active');
        card.hover(
            function() { $(this).css('box-shadow', '0 0 10px #0d6efd33'); },
            function() { if (!$(this).hasClass('active')) $(this).css('box-shadow', ''); }
        );
        leftCol.append(card);
    });

    row.append(leftCol, rightCol);
    container.append(row);

    // Render preview diagrams for all cards
    setTimeout(() => {
        state.entityDefinitions.forEach(definition => {
            const container = document.querySelector(`.definition-card[data-definition-id="${definition._id}"] .definition-preview`);
            if (container) {
                ensureEntityTypesArray(definition);
                renderJointJSDiagram(container.id, definition);
            }
        });
    }, 0);

    // Render details for the first definition by default
    if (state.entityDefinitions.length > 0) {
        renderDefinitionDetails(state.entityDefinitions[0]);
    }
}

function renderDefinitionDetails(definition) {
    const panel = $('#definition-details-panel');
    panel.empty();
    // Inline editable name/description
    panel.append(`
        <div class="d-flex align-items-center mb-2">
            <h4 class="me-2 editable-field" id="def-name" contenteditable="true" title="Click to edit name">${definition.name}</h4>
            <span class="badge bg-${definition.status === 'active' ? 'success' : 'warning'}">${definition.status}</span>
        </div>
        <div class="mb-3">
            <span class="editable-field text-muted" id="def-desc" contenteditable="true" title="Click to edit description">${definition.description || ''}</span>
        </div>
    `);
    // Edit/Delete buttons
    panel.append(`
        <div class="mb-3">
            <button class="btn btn-primary me-2 edit-definition" data-definition-id="${definition._id}"><i class="fas fa-edit"></i> Edit</button>
            <button class="btn btn-danger delete-definition" data-definition-id="${definition._id}"><i class="fas fa-trash"></i> Delete</button>
        </div>
    `);
    // Large diagram
    panel.append('<div id="definition-details-diagram" class="cytoscape-diagram mb-3" style="height:350px;"></div>');
    setTimeout(() => {
        const diagram = document.getElementById('definition-details-diagram');
        if (diagram) {
            ensureEntityTypesArray(definition);
            renderJointJSDiagram(diagram.id, definition);
        }
    }, 0);
    // Entity Types Table with tooltips
    let typesTable = `<h5>Entity Types <i class='fas fa-info-circle text-info' title='Types of entities in this definition'></i></h5><table class="table table-sm"><thead><tr><th>Type</th><th>Description</th><th>Required Attributes</th><th>Designation</th></tr></thead><tbody>`;
    Object.entries(definition.structure.entityTypes).forEach(([type, info]) => {
        typesTable += `<tr title="${info.description || ''}"><td><i class='fas fa-cube text-secondary me-1'></i>${type}</td><td>${info.description || '-'}</td><td>${(info.requiredAttributes || []).join(', ') || '-'}</td><td>${info.designation || '-'}</td></tr>`;
    });
    typesTable += '</tbody></table>';
    panel.append(typesTable);
    // Relationships Table with tooltips
    let relTable = `<h5>Relationships <i class='fas fa-info-circle text-info' title='Allowed parent-child relationships'></i></h5><table class="table table-sm"><thead><tr><th>Parent Type</th><th>Child Type</th><th>Min</th><th>Max</th></tr></thead><tbody>`;
    (definition.relationships || []).forEach(rel => {
        relTable += `<tr title="${rel.parentType} can have ${rel.childType} as child"><td><i class='fas fa-arrow-down text-success me-1'></i>${rel.parentType}</td><td>${rel.childType}</td><td>${rel.constraints?.minChildren || '0'}</td><td>${rel.constraints?.maxChildren || '∞'}</td></tr>`;
    });
    relTable += '</tbody></table>';
    panel.append(relTable);

    // Inline editing save on blur
    panel.find('.editable-field').on('blur', function() {
        const newName = $('#def-name').text().trim();
        const newDesc = $('#def-desc').text().trim();
        if (newName !== definition.name || newDesc !== (definition.description || '')) {
            showSpinner();
            $.ajax({
                url: `${API_BASE_URL}/entity-definitions/${definition._id}`,
                method: 'PUT',
                contentType: 'application/json',
                data: JSON.stringify({ name: newName, description: newDesc })
            })
            .done(() => {
                showToast('Definition updated');
                definition.name = newName;
                definition.description = newDesc;
                // Update card name/desc in left panel
                $(`.definition-card[data-definition-id='${definition._id}'] .card-title`).text(newName);
                $(`.definition-card[data-definition-id='${definition._id}'] .card-text`).text(newDesc);
            })
            .fail(() => showToast('Failed to update definition', 'danger'))
            .always(() => hideSpinner());
        }
    });
    // Enable Bootstrap tooltips
    setTimeout(() => { $("[title]").tooltip({container: 'body'}); }, 100);
}

// Card click handler to update right panel
$(document).on('click', '.definition-card', function() {
    $('.definition-card').removeClass('active').css('box-shadow', '');
    $(this).addClass('active').css('box-shadow', '0 0 10px #0d6efd33');
    const defId = $(this).data('definition-id');
    const definition = state.entityDefinitions.find(d => d._id === defId);
    if (definition) renderDefinitionDetails(definition);
});

// Event Handlers
$(document).on('click', '#create-definition-btn', () => {
    $('#definition-form')[0].reset();
    $('#definition-form [name="_id"]').val('');
    $('#definition-modal').modal('show');
});

$(document).on('click', '#create-from-template-btn', () => {
    showSpinner();
    $.get(`${API_BASE_URL}/entities/templates`)
        .done(response => {
            const templates = response || [];
            if (templates.length > 0) {
                const templateList = $('#template-list');
                templateList.empty();
                
                templates.forEach(template => {
                    const item = $(`
                        <button type="button" class="list-group-item list-group-item-action" 
                                data-template-id="${template._id}">
                            <h6 class="mb-1">${template.name}</h6>
                            <p class="mb-1">${template.description || ''}</p>
                            <small>Type: ${template.type}</small>
                        </button>
                    `);
                    // Store the full template data in the element's data
                    item.data('template', template);
                    templateList.append(item);
                });
                
                $('#template-selection-modal').modal('show');
            } else {
                showToast('No templates available', 'warning');
            }
        })
        .fail(error => {
            console.error('Failed to load templates:', error);
            showToast('Failed to load templates', 'danger');
        })
        .always(() => hideSpinner());
});

$(document).on('click', '#template-list .list-group-item', function() {
    const template = $(this).data('template');
    // Hide list, show preview
    $('#template-list-view').addClass('d-none');
    $('#template-preview-view').removeClass('d-none');
    // Fill in details
    $('#template-preview-details').html(`
        <dl>
            <dt>Name</dt><dd>${template.name}</dd>
            <dt>Description</dt><dd>${template.description || 'No description'}</dd>
            <dt>Type</dt><dd>${template.type}</dd>
            <dt>Version</dt><dd>${template.version || '-'}</dd>
            <dt>Entity Types</dt><dd>${Object.keys(template.structure.entityTypes).join(', ')}</dd>
        </dl>
    `);
    // Render graph
    setTimeout(() => {
        const container = document.getElementById('template-preview-diagram');
        if (container) {
            container.innerHTML = '';
            renderJointJSDiagram(container.id, template);
        }
    }, 100);
    // Store template for use
    $('#use-template-btn').data('template', template);
});

// Back button handler
$(document).on('click', '#template-back-btn', function() {
    $('#template-preview-view').addClass('d-none');
    $('#template-list-view').removeClass('d-none');
});

// Use Template button handler
$(document).on('click', '#use-template-btn', function() {
    const template = $(this).data('template');
    $('#template-selection-modal').modal('hide');
    showSpinner();
    $.ajax({
        url: `${API_BASE_URL}/entity-definitions/from-template`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            templateId: template._id,
            companyId: state.currentCompany,
            name: template.name,
            description: template.description
        })
    })
    .done(() => {
        showToast('Template applied and definition created!');
        loadEntityDefinitions();
    })
    .fail(() => showToast('Failed to apply template', 'danger'))
    .always(() => hideSpinner());
});

$(document).on('click', '.edit-definition', function() {
    const definitionId = $(this).data('definition-id');
    const definition = state.entityDefinitions.find(d => d._id === definitionId);
    if (definition) openEditDefinitionModal(definition);
});

$(document).on('click', '#save-definition-btn', function() {
    const form = $('#definition-form');
    if (!form[0].checkValidity()) {
        form[0].reportValidity();
        return;
    }
    
    const formData = new FormData(form[0]);
    const definitionId = formData.get('_id');
    
    try {
        const data = {
            name: formData.get('name'),
            description: formData.get('description'),
            structure: JSON.parse(formData.get('structure')),
            relationships: JSON.parse(formData.get('relationships'))
        };
        
        if (!definitionId) {
            data.companyId = state.currentCompany;
        }
        
        showSpinner();
        $('#definition-modal').modal('hide');
        
        $.ajax({
            url: definitionId ? 
                `${API_BASE_URL}/entity-definitions/${definitionId}` :
                `${API_BASE_URL}/entity-definitions`,
            method: definitionId ? 'PUT' : 'POST',
            data: JSON.stringify(data),
            contentType: 'application/json'
        })
            .done(() => {
                showToast(`Entity definition ${definitionId ? 'updated' : 'created'} successfully`);
                loadEntityDefinitions();
            })
            .fail(error => {
                console.error('Failed to save definition:', error);
                showToast('Failed to save definition', 'danger');
            })
            .always(() => hideSpinner());
    } catch (e) {
        showToast('Invalid JSON in structure or relationships', 'danger');
    }
});

$(document).on('click', '.delete-definition', function() {
    const definitionId = $(this).data('definition-id');
    if (confirm('Are you sure you want to delete this entity definition? This may affect existing entities.')) {
        showSpinner();
        $.ajax({
            url: `${API_BASE_URL}/entity-definitions/${definitionId}`,
            method: 'DELETE'
        })
            .done(() => {
                showToast('Entity definition deleted successfully');
                loadEntityDefinitions();
            })
            .fail(() => showToast('Failed to delete definition', 'danger'))
            .always(() => hideSpinner());
    }
});

$(document).on('click', '.view-definition', function() {
    const definitionId = $(this).data('definition-id');
    const definition = state.entityDefinitions.find(d => d._id === definitionId);
    
    if (definition) {
        // Render diagram
        renderDefinitionDiagram(definition);
        
        // Render JSON structure
        $('#definition-structure-content').html(`
            <h6>Entity Types</h6>
            <pre><code>${JSON.stringify(definition.structure.entityTypes, null, 2)}</code></pre>
            
            <h6>Allowed Attributes</h6>
            <pre><code>${JSON.stringify(definition.structure.allowedAttributes, null, 2)}</code></pre>
            
            <h6>Validations</h6>
            <pre><code>${JSON.stringify(definition.structure.validations, null, 2)}</code></pre>
            
            <h6>Relationships</h6>
            <pre><code>${JSON.stringify(definition.relationships, null, 2)}</code></pre>
        `);
        
        // Render metadata schema
        renderMetadataSchema(definition);
        
        $('#definition-structure-modal').modal('show');
    }
});

function showTemplatePreview(template) {
    const previewModal = $('#template-preview-modal');
    
    // Update modal content
    previewModal.find('.template-name').text(template.name);
    previewModal.find('.template-description').text(template.description || 'No description available');
    previewModal.find('.template-types').text(Object.keys(template.structure.entityTypes).join(', '));
    previewModal.find('.template-version').text(template.version);
    
    // Show the modal first so the container is visible
    previewModal.modal('show');
    
    // Initialize diagram after modal is shown
    previewModal.on('shown.bs.modal', function () {
        const container = document.querySelector('#template-preview-modal .template-diagram');
        container.style.height = '400px';
        renderJointJSDiagram(container.id, template);
    });
    
    // Store template data for the "Use Template" button
    previewModal.find('.use-template').data('template', template);
}

// --- New Entity Definition Editor Logic ---

// State for editing
let editDefState = null;

// Migration utility to ensure entityTypes is always an array
function ensureEntityTypesArray(definition) {
    if (!Array.isArray(definition.structure.entityTypes)) {
        definition.structure.entityTypes = Object.entries(definition.structure.entityTypes || {}).map(
            ([name, info]) => ({
                name,
                description: info.description || '',
                designation: info.designation || '',
                attributes: Array.isArray(info.attributes) ? info.attributes : [],
                requiredAttributes: Array.isArray(info.requiredAttributes) ? info.requiredAttributes : []
            })
        );
    }
}

// Open the edit modal with the selected definition
function openEditDefinitionModal(definition) {
    // Ensure structure and subfields exist
    definition.structure = definition.structure || {};
    ensureEntityTypesArray(definition);
    editDefState = JSON.parse(JSON.stringify(definition));
    // Render modal content as two columns
    const modalDialog = $('#definition-modal .modal-dialog');
    modalDialog.removeClass('modal-lg').addClass('modal-xl');
    // Move toolbar to header
    const modalHeader = $('#definition-modal .modal-header');
    modalHeader.find('.btn-group').remove(); // Remove any existing button group
    modalHeader.removeClass().addClass('modal-header d-flex align-items-center justify-content-end');
    modalHeader.find('.btn-toolbar').remove();
    modalHeader.find('.modal-title').after(`
        <div class="btn-group me-2" role="group">
            <button class="btn btn-outline-secondary" id="reset-definition-btn">Reset</button>
            <button class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button class="btn btn-primary" id="save-definition-btn"><i class="fas fa-floppy-disk"></i> Save</button>
        </div>
    `);
    const modalBody = $('#definition-modal .modal-body');
    modalBody.html(`
        <div class="row">
            <div class="col-md-6" id="edit-form-col">
                <ul class="nav nav-tabs mb-3" id="definition-tabs" role="tablist">
                    <li class="nav-item" role="presentation">
                        <button class="nav-link active" id="types-tab" data-bs-toggle="tab" data-bs-target="#types-panel" type="button" role="tab">Entity Types</button>
                    </li>
                    <li class="nav-item" role="presentation">
                        <button class="nav-link" id="relationships-tab" data-bs-toggle="tab" data-bs-target="#relationships-panel" type="button" role="tab">Relationships</button>
                    </li>
                </ul>
                <div class="tab-content">
                    <div class="tab-pane fade show active" id="types-panel" role="tabpanel">
                        <div id="edit-types-list"></div>
                        <button class="btn btn-success mt-2" id="add-entity-type-btn"><i class="fas fa-plus"></i> Add Type</button>
                    </div>
                    <div class="tab-pane fade" id="relationships-panel" role="tabpanel">
                        <div id="edit-relationships-list"></div>
                        <button class="btn btn-outline-success mt-2" id="add-relationship-btn"><i class="fas fa-plus"></i> Add Relationship</button>
                    </div>
                </div>
            </div>
            <div class="col-md-6 d-flex flex-column">
                <div class="mb-2"><strong>Live Preview</strong></div>
                <div id="edit-definition-preview" class="flex-grow-1" style="min-height:500px;"></div>
                <div id="edit-definition-legend" class="mt-2"></div>
            </div>
        </div>
    `);
    renderEditTypesList();
    renderEditRelationshipsList();
    renderEditDefinitionLegend();
    $('#definition-modal').modal('show');
    // Render the live preview only after the modal is fully shown
    $('#definition-modal').off('shown.bs.modal.jointjs').on('shown.bs.modal.jointjs', function() {
        renderEditDefinitionPreview();
    });
    // Reset button logic: fetch latest from backend
    $('#reset-definition-btn').off('click').on('click', function() {
        const id = definition._id;
        if (id) {
            showSpinner();
            $.get(`${API_BASE_URL}/entity-definitions/${id}`)
                .done(freshDef => {
                    openEditDefinitionModal(freshDef);
                })
                .fail(() => showToast('Failed to reset to latest from server', 'danger'))
                .always(() => hideSpinner());
        } else {
            openEditDefinitionModal(definition); // fallback for new definitions
        }
    });
}

// Render Entity Types Tab
function renderEditTypesList(focusType) {
    savePaperState();
    const container = $('#edit-types-list');
    container.empty();
    const types = editDefState.structure.entityTypes || [];
    types.forEach((typeObj, idx) => {
        const { name, description, designation } = typeObj;
        let required = Array.isArray(typeObj.requiredAttributes) ? typeObj.requiredAttributes : [];
        if ((!required || required.length === 0) && editDefState.structure && editDefState.structure.entityTypes) {
            const orig = editDefState.structure.entityTypes.find(t => t.name === name);
            if (orig && Array.isArray(orig.requiredAttributes)) {
                required = orig.requiredAttributes;
            }
        }
        let allowed = [];
        if (editDefState.structure && editDefState.structure.allowedAttributes && editDefState.structure.allowedAttributes[name]) {
            allowed = editDefState.structure.allowedAttributes[name];
        } else if (editDefState.structure && editDefState.structure.defaultAttributes && editDefState.structure.defaultAttributes[name]) {
            allowed = editDefState.structure.defaultAttributes[name];
        }
        const attrSet = new Set();
        typeObj.attributes.forEach(attr => attrSet.add(attr.name));
        required.forEach(attrName => attrSet.add(attrName));
        allowed.forEach(attrName => attrSet.add(attrName));
        const attrMap = {};
        typeObj.attributes.forEach(attr => { if (attr.name) attrMap[attr.name] = attr.type || 'string'; });
        attrSet.forEach(attrName => { if (!(attrName in attrMap)) attrMap[attrName] = 'string'; });
        const attrTable = $('<table class="table table-sm mb-0"><thead><tr><th style="width:60%">Name</th><th style="width:30%">Type</th><th style="width:10%"></th></tr></thead><tbody></tbody></table>');
        Array.from(attrSet).forEach(attrName => {
            const attrType = attrMap[attrName];
            const isRequired = required.includes(attrName);
            const attrRow = $(`
                <tr class="attribute-row">
                    <td><input type="text" class="form-control form-control-sm attr-name" value="${attrName}" placeholder="Attribute Name" ${isRequired ? 'readonly style="font-weight:bold;color:#0d6efd;"' : ''}></td>
                    <td>
                        <select class="form-select form-select-sm attr-type" ${isRequired ? 'disabled' : ''}>
                            <option value="string"${attrType === 'string' ? ' selected' : ''}>string</option>
                            <option value="number"${attrType === 'number' ? ' selected' : ''}>number</option>
                            <option value="boolean"${attrType === 'boolean' ? ' selected' : ''}>boolean</option>
                            <option value="date"${attrType === 'date' ? ' selected' : ''}>date</option>
                            <option value="object"${attrType === 'object' ? ' selected' : ''}>object</option>
                            <option value="array"${attrType === 'array' ? ' selected' : ''}>array</option>
                        </select>
                    </td>
                    <td>${isRequired ? '<span style="color:#0d6efd;font-weight:bold;">*</span>' : `<button class="btn btn-sm btn-link text-danger remove-attr-btn" title="Remove"><i class="fas fa-times"></i></button>`}</td>
                </tr>
            `);
            if (!isRequired) {
            attrRow.find('.remove-attr-btn').click(() => {
                    typeObj.attributes = typeObj.attributes.filter(a => a.name !== attrName);
                renderEditTypesList(name);
                renderEditDefinitionPreview();
            });
            attrRow.find('.attr-name').on('input', function() {
                    // Only update if not required
                    const idx = typeObj.attributes.findIndex(a => a.name === attrName);
                    if (idx !== -1) typeObj.attributes[idx].name = $(this).val();
                renderEditDefinitionPreview();
            });
                attrRow.find('.attr-type').on('change', function() {
                    const idx = typeObj.attributes.findIndex(a => a.name === attrName);
                    if (idx !== -1) typeObj.attributes[idx].type = $(this).val();
            renderEditDefinitionPreview();
        });
            }
            attrTable.find('tbody').append(attrRow);
        });
        const tableHTML = `
            <div xmlns='http://www.w3.org/1999/xhtml' style='width:${nodeWidth-2}px;'>
                <div style='font-weight:bold;font-size:15px;text-align:center;padding:4px 0 2px 0;border-bottom:1px solid #bbb;'>${name}</div>
                <table style='width:100%;border-collapse:collapse;'>
                    <thead><tr style='background:#f3f3f3;'><th style='font-size:13px;padding:2px 8px 2px 8px;text-align:left;'>Attribute</th><th style='font-size:13px;padding:2px 8px 2px 8px;text-align:left;'>Type</th></tr></thead>
                    <tbody>${attrTable.find('tbody').html()}</tbody>
                </table>
            </div>
        `;
        const nodeHeight = nodeHeader + (attributes.length+1) * rowHeight + 12;
        // Use custom markup with foreignObject
        const rect = new joint.shapes.standard.Rectangle({
            position: { x: xStart, y: yStart + idx * yGap },
            size: { width: nodeWidth, height: nodeHeight },
            attrs: {
                body: { fill: '#fff', stroke: '#0d6efd', strokeWidth: 2 },
                label: { text: '' },
                fo: { html: tableHTML }
            },
            markup: [
                {
                    tagName: 'rect',
                    selector: 'body'
                },
                {
                    tagName: 'foreignObject',
                    selector: 'fo',
                    attributes: { width: nodeWidth, height: nodeHeight, x: 0, y: 0 }
                }
            ]
        });
        rect.addTo(graph);
        typeNodes[name] = rect;
    });

    // 2. Add relationship links (solid lines)
    (definition.relationships || []).forEach(rel => {
        if (typeNodes[rel.parentType] && typeNodes[rel.childType]) {
            const relLink = new joint.shapes.standard.Link();
            relLink.source(typeNodes[rel.parentType]);
            relLink.target(typeNodes[rel.childType]);
            relLink.attr({
                line: {
                    stroke: '#0d6efd',
                    strokeWidth: 2,
                    targetMarker: { type: 'path', d: 'M 10 -5 0 0 10 5 z', fill: '#0d6efd' }
                }
            });
            // Add label for min..max
            const min = rel.constraints?.minChildren || '0';
            const max = rel.constraints?.maxChildren || '∞';
            relLink.appendLabel({
                attrs: {
                    text: {
                        text: `${min}..${max}`,
                        fill: '#333',
                        fontSize: 14,
                        fontWeight: 'bold'
                    }
                },
                position: 0.5
            });
            relLink.addTo(graph);
        }
    });

    // --- Improved Layout: Use DirectedGraph for alignment ---
    if (window.joint && joint.layout && joint.layout.DirectedGraph) {
        joint.layout.DirectedGraph.layout(graph, {
            setLinkVertices: false,
            rankDir: 'TB',
            nodeSep: 80,
            rankSep: 120,
            marginX: 40,
            marginY: 40
        });
    }

    // Optional: fit content
    paper.scaleContentToFit({ padding: 20, preserveAspectRatio: true });
    // Add subtle border
    newContainer.style.border = '1.5px solid #dee2e6';
    newContainer.style.background = '#f8f9fa';
    newContainer.style.borderRadius = '8px';

    currentPaper = paper;
}

// Add Type
$(document).on('click', '#add-entity-type-btn', function() {
    let types = editDefState.structure.entityTypes;
    if (!Array.isArray(types)) types = editDefState.structure.entityTypes = [];
    let idx = 1;
    let newType = `Type${idx}`;
    while (types.some(t => t.name === newType)) { idx++; newType = `Type${idx}`; }
    types.push({ name: newType, description: '', designation: '', requiredAttributes: [] });
    renderEditTypesList(newType);
    renderEditDefinitionPreview();
});

// Render Attributes Tab
function renderEditAttributesList() {
    const container = $('#edit-attributes-list');
    container.empty();
    const allowedAttrs = editDefState.structure.allowedAttributes || {};
    const types = Object.keys(editDefState.structure.entityTypes);
    types.forEach(type => {
        const attrs = allowedAttrs[type] || [];
        const row = $(
            `<div class="mb-2">
                <strong>${type}</strong>
                <div class="d-flex flex-wrap gap-2 mt-1 attr-list"></div>
                <button class="btn btn-sm btn-outline-success mt-1 add-attr-btn" data-type="${type}"><i class="fas fa-plus"></i> Add Attribute</button>
            </div>`
        );
        const attrList = row.find('.attr-list');
        attrs.forEach((attr, idx) => {
            const pill = $(
                `<span class="badge bg-secondary me-1 attr-pill" style="font-size:1em;">
                    <span contenteditable="true" class="attr-name">${attr}</span>
                    <i class="fas fa-times ms-1 remove-attr-btn" style="cursor:pointer;"></i>
                </span>`
            );
            pill.find('.remove-attr-btn').click(() => {
                allowedAttrs[type].splice(idx, 1);
                renderEditAttributesList();
                renderEditDefinitionPreview();
            });
            pill.find('.attr-name').on('blur', function() {
                const newName = $(this).text().trim();
                if (newName && newName !== attr) {
                    allowedAttrs[type][idx] = newName;
                    renderEditAttributesList();
                    renderEditDefinitionPreview();
                }
            });
            attrList.append(pill);
        });
        row.find('.add-attr-btn').click(() => {
            allowedAttrs[type] = allowedAttrs[type] || [];
            allowedAttrs[type].push('NewAttribute');
            renderEditAttributesList();
            renderEditDefinitionPreview();
        });
        container.append(row);
    });
    // Scroll Live Preview into view after rendering
    const livePreview = document.getElementById('edit-definition-preview');
    if (livePreview) {
        livePreview.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

// Render Relationships Tab
function renderEditRelationshipsList() {
    const container = $('#edit-relationships-list');
    container.empty();
    const rels = editDefState.relationships || [];
    const types = (editDefState.structure.entityTypes || []).map(t => t.name);
    rels.forEach((rel, idx) => {
        const row = $(`
            <div class="card mb-2">
                <div class="card-body p-2 d-flex align-items-center">
                    <select class="form-select form-select-sm me-2 parent-type" style="max-width:120px;"></select>
                    <span class="me-2">→</span>
                    <select class="form-select form-select-sm me-2 child-type" style="max-width:120px;"></select>
                    <input type="number" class="form-control form-control-sm me-2 min-children" value="${rel.constraints?.minChildren || 0}" min="0" style="max-width:60px;" title="Min children">
                    <input type="number" class="form-control form-control-sm me-2 max-children" value="${rel.constraints?.maxChildren || ''}" min="0" style="max-width:60px;" title="Max children">
                    <button class="btn btn-sm btn-danger remove-rel-btn" title="Remove"><i class="fas fa-trash"></i></button>
                </div>
            </div>
        `);
        // Populate selects
        types.forEach(t => {
            row.find('.parent-type').append(`<option value="${t}"${rel.parentType===t?' selected':''}>${t}</option>`);
            row.find('.child-type').append(`<option value="${t}"${rel.childType===t?' selected':''}>${t}</option>`);
        });
        // Handlers
        row.find('.parent-type').on('change', function() {
            rel.parentType = $(this).val();
            renderEditDefinitionPreview();
        });
        row.find('.child-type').on('change', function() {
            rel.childType = $(this).val();
            renderEditDefinitionPreview();
        });
        row.find('.min-children').on('input', function() {
            rel.constraints = rel.constraints || {};
            rel.constraints.minChildren = parseInt($(this).val()) || 0;
            renderEditDefinitionPreview();
        });
        row.find('.max-children').on('input', function() {
            rel.constraints = rel.constraints || {};
            rel.constraints.maxChildren = parseInt($(this).val()) || undefined;
            renderEditDefinitionPreview();
        });
        row.find('.remove-rel-btn').click(() => {
            rels.splice(idx, 1);
            renderEditRelationshipsList();
            renderEditDefinitionPreview();
        });
        container.append(row);
    });
}
// Add Relationship
$(document).on('click', '#add-relationship-btn', function() {
    const types = (editDefState.structure.entityTypes || []).map(t => t.name);
    if (types.length < 2) return;
    editDefState.relationships = editDefState.relationships || [];
    editDefState.relationships.push({ parentType: types[0], childType: types[1], constraints: { minChildren: 0, maxChildren: 1 } });
    renderEditRelationshipsList();
    renderEditDefinitionPreview();
});

// Live Preview and Legend
function renderEditDefinitionPreview() {
    savePaperState();
    renderJointJSDiagram('edit-definition-preview', editDefState);
}
function renderEditDefinitionLegend() {
    $('#edit-definition-legend').html(`
        <span class='me-3'><i class='fas fa-cube text-secondary'></i> Entity Type</span>
        <span class='me-3'><i class='fas fa-arrow-down text-success'></i> Relationship</span>
        <span class='me-3'><span class='badge bg-secondary'>Attr</span> Attribute</span>
    `);
}

// Save handler
$(document).on('click', '#save-definition-btn', function() {
    showSpinner();
    $.ajax({
        url: `${API_BASE_URL}/entity-definitions/${editDefState._id}`,
        method: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify({
            name: editDefState.name,
            description: editDefState.description,
            structure: editDefState.structure,
            relationships: editDefState.relationships
        })
    })
    .done(() => {
        showToast('Definition updated');
        $('#definition-modal').modal('hide');
        loadEntityDefinitions();
    })
    .fail(() => showToast('Failed to update definition', 'danger'))
    .always(() => hideSpinner());
});

// --- JointJS Diagram Rendering ---
function renderJointJSDiagram(containerId, definition) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';

    // Remove any previous event listeners by replacing the container node
    const newContainer = container.cloneNode(false);
    container.parentNode.replaceChild(newContainer, container);

    // Create JointJS graph and paper
    const graph = new joint.dia.Graph();
    const paper = new joint.dia.Paper({
        el: newContainer,
        model: graph,
        width: newContainer.offsetWidth,
        height: newContainer.offsetHeight,
        gridSize: 10,
        drawGrid: true,
        background: { color: '#f8f9fa' }
    });
    // Set a lower default zoom for modal
    if (lastPaperScale === 1) lastPaperScale = 0.7;
    paper.scale(lastPaperScale);
    paper.translate(lastPaperTranslate.x, lastPaperTranslate.y);
    // Mouse wheel zoom (attach only once)
    newContainer.addEventListener('wheel', function(e) {
        if (e.ctrlKey || e.metaKey) return; // allow browser zoom
        e.preventDefault();
        const delta = e.deltaY || e.detail || e.wheelDelta;
        if (delta < 0) {
            lastPaperScale = Math.min(lastPaperScale + 0.1, 2);
        } else {
            lastPaperScale = Math.max(lastPaperScale - 0.1, 0.3);
        }
        paper.scale(lastPaperScale);
    }, { passive: false });
    // Enable robust panning using JointJS events (cell or blank)
    let panStart = null;
    let panOffset = null;
    paper.on('cell:pointerdown blank:pointerdown', function(evt, x, y) {
        panStart = { x, y };
        panOffset = paper.translate();
        paper.svg.style.cursor = 'grabbing';
    });
    paper.on('cell:pointermove blank:pointermove', function(evt, x, y) {
        if (!panStart) return;
        const dx = x - panStart.x;
        const dy = y - panStart.y;
        paper.translate(panOffset.x + dx, panOffset.y + dy);
        lastPaperTranslate = { x: panOffset.x + dx, y: panOffset.y + dy };
    });
    paper.on('cell:pointerup blank:pointerup', function() {
        panStart = null;
        panOffset = null;
        paper.svg.style.cursor = '';
    });
    // Layout helpers
    const typeNodes = {};
    const nodeWidth = 220, nodeHeader = 36, rowHeight = 26;
    const xStart = 40, yStart = 40, yGap = 160;
    // Sort entity types so that 'plant' is rendered first (on top)
    let entityTypes = (definition.structure.entityTypes || []);
    entityTypes = [...entityTypes];
    entityTypes.sort((a, b) => {
        if (a.name === 'plant') return -1;
        if (b.name === 'plant') return 1;
        return 0;
    });
    entityTypes.forEach((typeObj, idx) => {
        // Merge all unique attribute names from attributes, requiredAttributes, allowedAttributes, defaultAttributes
        const attributes = Array.isArray(typeObj.attributes) ? typeObj.attributes : [];
        let required = Array.isArray(typeObj.requiredAttributes) ? typeObj.requiredAttributes : [];
        if ((!required || required.length === 0) && definition.structure && definition.structure.entityTypes) {
            const orig = definition.structure.entityTypes[typeObj.name];
            if (orig && Array.isArray(orig.requiredAttributes)) {
                required = orig.requiredAttributes;
            }
        }
        let allowed = [];
        if (definition.structure && definition.structure.allowedAttributes && definition.structure.allowedAttributes[typeObj.name]) {
            allowed = definition.structure.allowedAttributes[typeObj.name];
        } else if (definition.structure && definition.structure.defaultAttributes && definition.structure.defaultAttributes[typeObj.name]) {
            allowed = definition.structure.defaultAttributes[typeObj.name];
        }
        const attrSet = new Set();
        attributes.forEach(attr => attrSet.add(attr.name));
        required.forEach(attrName => attrSet.add(attrName));
        allowed.forEach(attrName => attrSet.add(attrName));
        const attrMap = {};
        attributes.forEach(attr => { if (attr.name) attrMap[attr.name] = attr.type || '-'; });
        attrSet.forEach(attrName => { if (!(attrName in attrMap)) attrMap[attrName] = '-'; });
        let tableRows = '';
        Array.from(attrSet).forEach(attrName => {
            const attrType = attrMap[attrName];
            const isRequired = required.includes(attrName);
            tableRows += `<tr><td style='padding:2px 8px;font-size:13px;${isRequired ? "font-weight:bold;color:#0d6efd;" : ''}'>${attrName}${isRequired ? ' *' : ''}</td><td style='padding:2px 8px;font-size:13px;'>${attrType}</td></tr>`;
        });
        const tableHTML = `
            <div xmlns='http://www.w3.org/1999/xhtml' style='width:${nodeWidth-2}px;'>
                <div style='font-weight:bold;font-size:15px;text-align:center;padding:4px 0 2px 0;border-bottom:1px solid #bbb;'>${typeObj.name}</div>
                <table style='width:100%;border-collapse:collapse;'>
                    <thead><tr style='background:#f3f3f3;'><th style='font-size:13px;padding:2px 8px 2px 8px;text-align:left;'>Attribute</th><th style='font-size:13px;padding:2px 8px 2px 8px;text-align:left;'>Type</th></tr></thead>
                    <tbody>${tableRows}</tbody>
                </table>
            </div>
        `;
        const nodeHeight = nodeHeader + (attributes.length+1) * rowHeight + 12;
        // Use custom markup with foreignObject
        const rect = new joint.shapes.standard.Rectangle({
            position: { x: xStart, y: yStart + idx * yGap },
            size: { width: nodeWidth, height: nodeHeight },
            attrs: {
                body: { fill: '#fff', stroke: '#0d6efd', strokeWidth: 2 },
                label: { text: '' },
                fo: { html: tableHTML }
            },
            markup: [
                {
                    tagName: 'rect',
                    selector: 'body'
                },
                {
                    tagName: 'foreignObject',
                    selector: 'fo',
                    attributes: { width: nodeWidth, height: nodeHeight, x: 0, y: 0 }
                }
            ]
        });
        rect.addTo(graph);
        typeNodes[typeObj.name] = rect;
    });

    // 2. Add relationship links (solid lines)
    (definition.relationships || []).forEach(rel => {
        if (typeNodes[rel.parentType] && typeNodes[rel.childType]) {
            const relLink = new joint.shapes.standard.Link();
            relLink.source(typeNodes[rel.parentType]);
            relLink.target(typeNodes[rel.childType]);
            relLink.attr({
                line: {
                    stroke: '#0d6efd',
                    strokeWidth: 2,
                    targetMarker: { type: 'path', d: 'M 10 -5 0 0 10 5 z', fill: '#0d6efd' }
                }
            });
            // Add label for min..max
            const min = rel.constraints?.minChildren || '0';
            const max = rel.constraints?.maxChildren || '∞';
            relLink.appendLabel({
                attrs: {
                    text: {
                        text: `${min}..${max}`,
                        fill: '#333',
                        fontSize: 14,
                        fontWeight: 'bold'
                    }
                },
                position: 0.5
            });
            relLink.addTo(graph);
        }
    });

    // --- Improved Layout: Use DirectedGraph for alignment ---
    if (window.joint && joint.layout && joint.layout.DirectedGraph) {
    joint.layout.DirectedGraph.layout(graph, {
        setLinkVertices: false,
        rankDir: 'TB',
        nodeSep: 80,
        rankSep: 120,
        marginX: 40,
        marginY: 40
    });
    }

    // Optional: fit content
    paper.scaleContentToFit({ padding: 20, preserveAspectRatio: true });
    // Add subtle border
    newContainer.style.border = '1.5px solid #dee2e6';
    newContainer.style.background = '#f8f9fa';
    newContainer.style.borderRadius = '8px';

    currentPaper = paper;
} 