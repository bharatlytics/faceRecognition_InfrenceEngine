import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # MongoDB Configuration
    MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb+srv://bharatlytics:nN9AEW7exNdqoQ3r@cluster0.tato9.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
    DATABASE_NAME = os.getenv('DATABASE_NAME', 'factorylyticsDB')
    
    # Application Configuration
    COMPANY_NAME = "Bharatlytics"  # This is what we want to make configurable
    
    # Server Configuration
    DEBUG = os.getenv('DEBUG', 'True') == 'True'
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', 5000))

    # File Storage Configuration
    UPLOAD_FOLDER = 'uploads'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # Allowed embedding models
    ALLOWED_MODELS = ['buffalo_l', 'mobile_facenet_v1']