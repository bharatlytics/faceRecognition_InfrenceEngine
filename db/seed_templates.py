from bson import ObjectId
from datetime import datetime

# Default templates that will be seeded
DEFAULT_TEMPLATES = [
    {
        "name": "Manufacturing Plant",
        "type": "manufacturing",
        "description": "Standard template for manufacturing facilities with plants, lines, and workstations",
        "version": "1.0",
        "structure": {
            "entityTypes": {
                "business_unit": {
                    "description": "Business Unit",
                    "requiredAttributes": ["buCode"],
                    "allowedValues": {
                        "type": ["production", "sales", "rd"]
                    },
                    "designation": "BU_HEAD"  # Single clear designation for each entity type
                },
                "plant": {
                    "description": "Manufacturing plant facility",
                    "requiredAttributes": ["location", "plantCode"],
                    "allowedValues": {
                        "type": ["production", "assembly", "warehouse"]
                    },
                    "designation": "PLANT_HEAD"
                },
                "department": {
                    "description": "Department within plant",
                    "requiredAttributes": ["departmentCode"],
                    "allowedValues": {
                        "category": ["production", "quality", "maintenance", "logistics"]
                    },
                    "designation": "DEPT_HEAD"
                },
                "line": {
                    "description": "Production or assembly line",
                    "requiredAttributes": ["lineCode", "capacity"],
                    "allowedValues": {},
                    "designation": "LINE_SUPERVISOR"
                },
                "workstation": {
                    "description": "Individual workstation or machine",
                    "requiredAttributes": ["stationCode", "status"],
                    "allowedValues": {
                        "status": ["active", "inactive", "maintenance"]
                    },
                    "designation": "STATION_OPERATOR"
                }
            },
            "defaultAttributes": {
                "business_unit": ["buCode", "type", "region", "revenue_target"],
                "plant": ["location", "plantCode", "type", "capacity", "operatingHours"],
                "department": ["departmentCode", "category", "shift"],
                "line": ["lineCode", "capacity", "product", "cycleTime"],
                "workstation": ["stationCode", "status", "efficiency"]
            },
            "defaultValidations": {
                "buCode": "^BU\\d{3}$",
                "plantCode": "^PLT\\d{3}$",
                "departmentCode": "^DEP\\d{3}$",
                "lineCode": "^LN\\d{3}$",
                "stationCode": "^WS\\d{3}$"
            }
        },
        "relationships": [
            {
                "parentType": "business_unit",
                "childType": "plant",
                "cardinality": "one_to_many"
            },
            {
                "parentType": "plant",
                "childType": "department",
                "cardinality": "one_to_many"
            },
            {
                "parentType": "department",
                "childType": "line",
                "cardinality": "one_to_many"
            },
            {
                "parentType": "line",
                "childType": "workstation",
                "cardinality": "one_to_many"
            }
        ]
    },
    {
        "name": "Office Building",
        "type": "office",
        "description": "Template for office buildings with floors, zones, and workspaces",
        "version": "1.0",
        "structure": {
            "entityTypes": {
                "building": {
                    "description": "Office building",
                    "requiredAttributes": ["buildingCode", "address"],
                    "allowedValues": {
                        "type": ["corporate", "regional", "branch"]
                    }
                },
                "floor": {
                    "description": "Building floor",
                    "requiredAttributes": ["floorNumber"],
                    "allowedValues": {}
                },
                "zone": {
                    "description": "Floor zone or area",
                    "requiredAttributes": ["zoneCode", "purpose"],
                    "allowedValues": {
                        "purpose": ["workspace", "meeting", "utility", "recreation"]
                    }
                },
                "workspace": {
                    "description": "Individual workspace or room",
                    "requiredAttributes": ["workspaceId", "type"],
                    "allowedValues": {
                        "type": ["desk", "office", "meeting_room", "utility_room"]
                    }
                }
            },
            "defaultAttributes": {
                "building": ["buildingCode", "address", "type", "totalFloors", "capacity"],
                "floor": ["floorNumber", "capacity", "facilities"],
                "zone": ["zoneCode", "purpose", "area", "capacity"],
                "workspace": ["workspaceId", "type", "capacity", "equipment"]
            },
            "defaultValidations": {
                "buildingCode": "^BLD\\d{3}$",
                "floorNumber": "^\\d{1,2}$",
                "zoneCode": "^Z\\d{3}$",
                "workspaceId": "^WS\\d{4}$"
            }
        },
        "relationships": [
            {
                "parentType": "building",
                "childType": "floor",
                "constraints": {
                    "maxChildren": 50
                }
            },
            {
                "parentType": "floor",
                "childType": "zone",
                "constraints": {
                    "maxChildren": 10
                }
            },
            {
                "parentType": "zone",
                "childType": "workspace",
                "constraints": {
                    "maxChildren": 50
                }
            }
        ]
    }
]

def seed_templates(db):
    """
    Seed or update default templates in the database.
    This function is called at server startup.
    """
    template_collection = db['entityTemplates']  # Use the correct collection name

    for template in DEFAULT_TEMPLATES:
        try:
            # Check if template already exists (match by name and type)
            existing = template_collection.find_one({
                "name": template["name"],
                "type": template["type"]
            })

            # Add common fields
            template["status"] = "active"
            template["updatedAt"] = datetime.utcnow()

            if existing:
                # Update existing template if version is different
                if existing.get("version") != template["version"]:
                    template_collection.update_one(
                        {"_id": existing["_id"]},
                        {
                            "$set": {
                                **template,
                                "previousVersion": existing.get("version"),
                                "updatedAt": datetime.utcnow()
                            }
                        }
                    )
                    print(f"Updated template: {template['name']} to version {template['version']}")
                else:
                    print(f"Template already up to date: {template['name']} (v{template['version']})")
            else:
                # Create new template
                template["createdAt"] = datetime.utcnow()
                template_collection.insert_one(template)
                print(f"Created new template: {template['name']} (v{template['version']})")
        except Exception as e:
            print(f"Error processing template {template['name']}: {str(e)}")
            continue

    return True 