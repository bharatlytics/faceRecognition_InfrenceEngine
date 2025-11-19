from pymongo import MongoClient
from gridfs import GridFS
from .seed_templates import seed_templates
from app.config.config import Config

# Initialize MongoDB client with configuration
print(f"Connecting to MongoDB at {Config.MONGODB_URI}...")
client = MongoClient(Config.MONGODB_URI)
db = client[Config.DATABASE_NAME]

# Collections
company_collection = db['companies']
entity_collection = db['entities']
asset_collection = db['assets']
employee_collection = db['employeeInfo']
entity_template_collection = db['entityTemplates']
entity_definition_collection = db['entityDefinitions']
embedding_jobs_collection = db['embeddingJobs']
visitor_collection = db['visitors']
visit_collection = db['visits']

# Initialize GridFS for different file types
employee_image_fs = GridFS(db, collection='employee_images')
visitor_image_fs = GridFS(db, collection='visitor_images')
employee_embedding_fs = GridFS(db, collection='employee_embeddings')
visitor_embedding_fs = GridFS(db, collection='visitor_embeddings')

# Export collections
__all__ = [
    'company_collection',
    'entity_collection',
    'asset_collection',
    'employee_collection',
    'entity_template_collection',
    'entity_definition_collection'
]

def init_db():
    """Initialize database with indexes and seed data."""
    try:
        # Dictionary of collections and their required indexes
        collection_indexes = {
            entity_collection: [
                ('companyId', 1),
                ('parentId', 1),
                ('path', 1),
                ('type', 1)
            ],
            employee_collection: [
                ('companyId', 1),
                ('employeeId', 1),
                ('email', 1),
                ('phone', 1)
            ],
            visitor_collection: [
                ('companyId', 1),
                ('visitorId', 1),
                ('email', 1),
                ('phone', 1)
            ],
            visit_collection: [
                ('companyId', 1),
                ('visitorId', 1),
                ('employeeId', 1),
                ('visitDate', 1),
                ('status', 1)
            ],
            entity_template_collection: [
                ('type', 1),
                ('status', 1)
            ],
            entity_definition_collection: [
                ('companyId', 1),
                ('status', 1)
            ],
            embedding_jobs_collection: [
                ('status', 1),
                ('createdAt', 1),
                ('companyId', 1),
                ('employeeId', 1),
                ('visitorId', 1)
            ]
        }

        # Create missing indexes for each collection
        for collection, indexes in collection_indexes.items():
            try:
                # Get existing indexes
                existing_indexes = set()
                for idx in collection.list_indexes():
                    # Extract the keys from the index
                    for key in idx['key'].keys():
                        if key != '_id':  # Skip the default _id index
                            existing_indexes.add(key)
                
                # Create only missing indexes
                for index in indexes:
                    if index[0] not in existing_indexes:
                        print(f"Creating missing index {index[0]} for {collection.name}")
                        collection.create_index([index], background=True)
                    else:
                        print(f"Index {index[0]} already exists for {collection.name}")

            except Exception as e:
                print(f"Warning: Error handling indexes for {collection.name}: {str(e)}")
                continue

        # Seed templates at startup
        print("Checking entity templates...")
        seed_templates(db)
        print("Template check completed.")
        
        print("Database initialization completed successfully.")
        return True
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        return False 