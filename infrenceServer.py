import cv2
import os
import numpy as np
import pickle
import multiprocessing as mp
from queue import Empty, Queue
from threading import Thread, Lock
import time
from datetime import datetime, timedelta
from insightface.app import FaceAnalysis
from pymongo import MongoClient
from gridfs import GridFS
from bson import ObjectId
from flask import Flask, request, jsonify
from flask_cors import CORS
from app.config.config import Config
import logging
from typing import Dict, List, Optional, Tuple
import signal
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('face_recognition.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

class EmbeddingManager:
    """Manages face embeddings with real-time synchronization from MongoDB."""
    
    def __init__(self, mongodb_uri: str, database_name: str):
        self.client = MongoClient(mongodb_uri)
        self.db = self.client[database_name]
        self.employee_collection = self.db['employeeInfo']
        self.visitor_collection = self.db['visitors']
        self.employee_embedding_fs = GridFS(self.db, collection='employee_embeddings')
        self.visitor_embedding_fs = GridFS(self.db, collection='visitor_embeddings')
        
        # Thread-safe storage for embeddings
        self.embeddings_lock = Lock()
        self.embeddings: Dict[str, np.ndarray] = {}
        self.employee_metadata: Dict[str, Dict] = {}
        self.last_sync_time = None  # Will be set after initial load
        self.is_initial_load = True
        
        # Sync configuration
        self.sync_interval = 30  # seconds
        self.running = False
        self.sync_thread = None
        
        # Perform initial load
        self._initial_load()
    
    def _initial_load(self):
        """Load all existing embeddings on startup."""
        try:
            logger.info("Starting initial embedding load...")
            
            # Get all active employees
            all_employees = self._get_all_active_employees()
            # Get all visitors
            all_visitors = self._get_all_visitors()
            
            # Load all embeddings
            self._load_updated_embeddings(all_employees, all_visitors)
            
            # Count employees and visitors
            with self.embeddings_lock:
                employee_count = sum(1 for meta in self.employee_metadata.values() if meta['type'] == 'employee')
                visitor_count = sum(1 for meta in self.employee_metadata.values() if meta['type'] == 'visitor')
            
            # Set last sync time after initial load
            self.last_sync_time = datetime.utcnow()
            self.is_initial_load = False
            
            logger.info(f"Initial load completed. Loaded {len(self.embeddings)} embeddings "
                        f"({employee_count} employees, {visitor_count} visitors)")
            
        except Exception as e:
            logger.error(f"Error during initial load: {e}")
            # Set last sync time even if initial load fails
            self.last_sync_time = datetime.utcnow()
            self.is_initial_load = False
            
    def _get_all_active_employees(self) -> List[Dict]:
        """Get all active employees with embeddings."""
        query = {
            'status': 'active',
            'blacklisted': False,
            'employeeEmbeddings.buffalo_l.status': 'done'
        }
        return list(self.employee_collection.find(query))
        
    def _get_all_visitors(self) -> List[Dict]:
        """Get all visitors with embeddings."""
        # First, let's debug what's in the collection
        total_visitors = self.visitor_collection.count_documents({})
        logger.info(f"Total visitors in collection: {total_visitors}")
        
        # Check different query variations
        queries_to_test = [
            {'visitorEmbeddings.buffalo_l.status': 'done'},
            {'visitorEmbeddings.buffalo_l': {'$exists': True}},
            {'visitorEmbeddings': {'$exists': True}},
            {}  # Get all visitors to see structure
        ]
        
        for i, query in enumerate(queries_to_test):
            count = self.visitor_collection.count_documents(query)
            logger.info(f"Query {i+1} {query}: {count} visitors found")
        
        # Get a sample visitor to inspect structure
        sample_visitor = self.visitor_collection.find_one({})
        if sample_visitor:
            logger.info(f"Sample visitor structure: {sample_visitor.get('visitorEmbeddings', 'No visitorEmbeddings field')}")
        
        # Use the main query but with debugging
        query = {'visitorEmbeddings.buffalo_l.status': 'done'}
        visitors = list(self.visitor_collection.find(query))
        
        logger.info(f"Found {len(visitors)} visitors with embeddings status 'done'")
        
        # Additional debugging for each visitor
        for visitor in visitors:
            visitor_id = visitor.get('_id')
            embeddings_info = visitor.get('visitorEmbeddings', {})
            buffalo_info = embeddings_info.get('buffalo_l', {})
            
            logger.info(f"Visitor {visitor_id}:")
            logger.info(f"  - visitorEmbeddings exists: {'visitorEmbeddings' in visitor}")
            logger.info(f"  - buffalo_l exists: {'buffalo_l' in embeddings_info}")
            logger.info(f"  - status: {buffalo_info.get('status', 'missing')}")
            logger.info(f"  - embeddingId: {buffalo_info.get('embeddingId', 'missing')}")
        
        # If no visitors found with status 'done', try a broader search
        if not visitors:
            logger.warning("No visitors found with status 'done', trying broader search...")
            broader_query = {'visitorEmbeddings.buffalo_l': {'$exists': True}}
            broader_visitors = list(self.visitor_collection.find(broader_query))
            logger.info(f"Found {len(broader_visitors)} visitors with buffalo_l embeddings (any status)")
            
            # Check what statuses exist
            for visitor in broader_visitors:
                status = visitor.get('visitorEmbeddings', {}).get('buffalo_l', {}).get('status', 'no status')
                embedding_id = visitor.get('visitorEmbeddings', {}).get('buffalo_l', {}).get('embeddingId', 'no embeddingId')
                logger.info(f"Visitor {visitor['_id']}: status='{status}', embeddingId='{embedding_id}'")
        
        return visitors
        
    def start_sync(self):
        """Start the background synchronization thread."""
        if self.running:
            return
            
        self.running = True
        self.sync_thread = Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()
        logger.info("Embedding sync thread started")
        
    def stop_sync(self):
        """Stop the background synchronization thread."""
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)
        logger.info("Embedding sync thread stopped")
        
    def _sync_loop(self):
        """Background thread that periodically syncs embeddings."""
        while self.running:
            try:
                self._sync_embeddings()
                time.sleep(self.sync_interval)
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                time.sleep(5)  # Wait before retrying
                
    def _sync_embeddings(self):
        """Synchronize embeddings from MongoDB."""
        try:
            if self.last_sync_time is None:
                logger.warning("Sync called before initial load completed")
                return
                
            # Get all active employees and visitors updated since last sync
            updated_employees = self._get_updated_employees()
            updated_visitors = self._get_updated_visitors()
            
            # Remove inactive/deleted employees
            self._remove_inactive_employees()
            
            # Load new/updated embeddings
            if updated_employees or updated_visitors:
                self._load_updated_embeddings(updated_employees, updated_visitors)
                logger.info(f"Synced {len(updated_employees)} employees and {len(updated_visitors)} visitors")
            
            self.last_sync_time = datetime.utcnow()
            logger.debug(f"Sync completed. Total embeddings: {len(self.embeddings)}")
            
        except Exception as e:
            logger.error(f"Error syncing embeddings: {e}")
            
    def _get_updated_employees(self) -> List[Dict]:
        """Get employees that were updated since last sync."""
        if self.last_sync_time is None:
            return []
            
        query = {
            'lastUpdated': {'$gte': self.last_sync_time},
            'status': 'active',
            'blacklisted': False,
            'employeeEmbeddings.buffalo_l.status': 'done'
        }
        return list(self.employee_collection.find(query))
        
    def _get_updated_visitors(self) -> List[Dict]:
        """Get visitors that were updated since last sync."""
        if self.last_sync_time is None:
            return []
            
        query = {
            'lastUpdated': {'$gte': self.last_sync_time},
            'visitorEmbeddings.buffalo_l.status': 'done'
        }
        return list(self.visitor_collection.find(query))
        
    def _remove_inactive_employees(self):
        """Remove embeddings for inactive or blacklisted employees."""
        with self.embeddings_lock:
            # Get all current employee IDs that should be removed
            inactive_query = {
                '$or': [
                    {'status': {'$ne': 'active'}},
                    {'blacklisted': True}
                ]
            }
            
            inactive_employees = self.employee_collection.find(inactive_query, {'_id': 1})
            inactive_ids = {str(emp['_id']) for emp in inactive_employees}
            
            # Remove inactive employees from embeddings
            removed_count = 0
            for emp_id in list(self.embeddings.keys()):
                if emp_id in inactive_ids:
                    del self.embeddings[emp_id]
                    if emp_id in self.employee_metadata:
                        del self.employee_metadata[emp_id]
                    removed_count += 1
                    
            if removed_count > 0:
                logger.info(f"Removed {removed_count} inactive employee embeddings")
                
    def _load_updated_embeddings(self, employees: List[Dict], visitors: List[Dict]):
        """Load embeddings for updated employees and visitors."""
        with self.embeddings_lock:
            # Load employee embeddings
            for employee in employees:
                try:
                    emp_id = str(employee['_id'])
                    emb_entry = employee['employeeEmbeddings']['buffalo_l']
                    
                    file = self.employee_embedding_fs.get(emb_entry['embeddingId'])
                    embedding = pickle.loads(file.read())
                    normalized_embedding = embedding / np.linalg.norm(embedding)
                    
                    self.embeddings[emp_id] = normalized_embedding
                    self.employee_metadata[emp_id] = {
                        'name': employee.get('employeeName', 'Unknown'),
                        'employeeId': employee.get('employeeId', 'Unknown'),
                        'email': employee.get('employeeEmail', ''),
                        'mobile': employee.get('employeeMobile', ''),
                        'type': 'employee',
                        'lastUpdated': employee.get('lastUpdated', datetime.utcnow())
                    }
                    logger.info(f"Loaded embedding for employee {emp_id}: {employee.get('employeeName', 'Unknown')}")
                    
                except Exception as e:
                    logger.error(f"Error loading employee embedding for {employee['_id']}: {e}")
                    
            # Load visitor embeddings with enhanced debugging
            for visitor in visitors:
                try:
                    visitor_id = str(visitor['_id'])
                    logger.info(f"Processing visitor {visitor_id}: {visitor.get('visitorName', 'Unknown')}")
                    
                    if 'visitorEmbeddings' not in visitor:
                        logger.warning(f"Skipping visitor {visitor_id}: no visitorEmbeddings field")
                        continue
                        
                    if 'buffalo_l' not in visitor['visitorEmbeddings']:
                        logger.warning(f"Skipping visitor {visitor_id}: no buffalo_l in visitorEmbeddings")
                        continue
                        
                    emb_entry = visitor['visitorEmbeddings']['buffalo_l']
                    
                    if 'embeddingId' not in emb_entry:
                        logger.warning(f"Skipping visitor {visitor_id}: no embeddingId in buffalo_l")
                        continue
                    
                    if 'status' not in emb_entry or emb_entry['status'] != 'done':
                        logger.warning(f"Skipping visitor {visitor_id}: status is '{emb_entry.get('status', 'missing')}', not 'done'")
                        continue
                    
                    embedding_id = emb_entry['embeddingId']
                    logger.info(f"Attempting to load visitor {visitor_id} with embeddingId {embedding_id}")
                    
                    # Try to get the file from GridFS
                    try:
                        file = self.visitor_embedding_fs.get(ObjectId(embedding_id))
                    except Exception as e:
                        logger.error(f"Failed to get embedding file for visitor {visitor_id}: {e}")
                        continue
                    
                    # Load and process the embedding
                    try:
                        embedding = pickle.loads(file.read())
                        normalized_embedding = embedding / np.linalg.norm(embedding)
                        
                        self.embeddings[visitor_id] = normalized_embedding
                        self.employee_metadata[visitor_id] = {
                            'name': visitor.get('visitorName', 'Unknown'),
                            'type': 'visitor',
                            'lastUpdated': visitor.get('lastUpdated', datetime.utcnow())
                        }
                        logger.info(f"Successfully loaded embedding for visitor {visitor_id}: {visitor.get('visitorName', 'Unknown')}")
                        
                    except Exception as e:
                        logger.error(f"Failed to process embedding data for visitor {visitor_id}: {e}")
                        continue
                    
                except Exception as e:
                    logger.error(f"Error loading visitor embedding for {visitor['_id']}: {e}")
                    import traceback
                    logger.error(f"Full traceback: {traceback.format_exc()}")
                    
    def get_embeddings_for_company(self, company_id: str) -> Tuple[Dict[str, np.ndarray], Dict[str, Dict]]:
        """Get embeddings and metadata for a specific company."""
        with self.embeddings_lock:
            # Filter embeddings by company
            company_embeddings = {}
            company_metadata = {}
            
            # Get employee embeddings for this company
            employees = self.employee_collection.find({
                'companyId': ObjectId(company_id),
                'status': 'active',
                'blacklisted': False
            }, {'_id': 1})
            
            employee_ids = {str(emp['_id']) for emp in employees}
            
            for emp_id in employee_ids:
                if emp_id in self.embeddings:
                    company_embeddings[emp_id] = self.embeddings[emp_id]
                    company_metadata[emp_id] = self.employee_metadata[emp_id]
                    
            # Get visitor embeddings for this company
            visitors = self.visitor_collection.find({
                'companyId': ObjectId(company_id)
            }, {'_id': 1})
            
            visitor_ids = {str(visitor['_id']) for visitor in visitors}
            
            for visitor_id in visitor_ids:
                if visitor_id in self.embeddings:
                    company_embeddings[visitor_id] = self.embeddings[visitor_id]
                    company_metadata[visitor_id] = self.employee_metadata[visitor_id]
                    
            logger.info(f"Company {company_id} embeddings: {len(company_embeddings)} total "
                       f"({len([k for k in company_metadata if company_metadata[k]['type'] == 'employee'])} employees, "
                       f"{len([k for k in company_metadata if company_metadata[k]['type'] == 'visitor'])} visitors)")
                    
            return company_embeddings, company_metadata
            
    def force_sync(self):
        """Force an immediate synchronization."""
        self._sync_embeddings()
        
    def get_stats(self) -> Dict:
        """Get statistics about current embeddings."""
        with self.embeddings_lock:
            employees = sum(1 for meta in self.employee_metadata.values() if meta['type'] == 'employee')
            visitors = sum(1 for meta in self.employee_metadata.values() if meta['type'] == 'visitor')
            
            return {
                'total_embeddings': len(self.embeddings),
                'employees': employees,
                'visitors': visitors,
                'last_sync': self.last_sync_time.isoformat() if self.last_sync_time else None,
                'initial_load_complete': not self.is_initial_load
            }

class FaceRecognitionProcessor:
    """Handles face recognition processing with optimized performance."""
    
    def __init__(self, embedding_manager: EmbeddingManager):
        self.embedding_manager = embedding_manager
        self.face_detector = None
        self.detection_threshold = 0.3
        self.recognition_threshold = 0.4
        
    def initialize_detector(self):
        """Initialize the face detection model."""
        if self.face_detector is None:
            self.face_detector = FaceAnalysis(
                name="buffalo_l", 
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
            )
            self.face_detector.prepare(ctx_id=0)
            
    def draw_enhanced_bounding_box(self, frame: np.ndarray, bbox: List[int], color: Tuple[int, int, int], 
                                 person_info: Dict, detection_score: float, recognition_score: float) -> np.ndarray:
        """Draw an enhanced HUD-style bounding box with person information."""
        overlay = frame.copy()
        x1, y1, x2, y2 = bbox
        thickness = 2
        
        # Draw semi-transparent bounding box
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)
        
        # Draw corner markers
        corner_length = 15
        corner_thickness = 3
        corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
        for corner in corners:
            cv2.line(frame, corner, (corner[0] + corner_length, corner[1]), color, corner_thickness)
            cv2.line(frame, corner, (corner[0], corner[1] + corner_length), color, corner_thickness)
            cv2.line(frame, (corner[0] + corner_length, corner[1]), (corner[0], corner[1] + corner_length), color, corner_thickness)
        
        # Draw confidence bars
        bar_x = x2 + 10
        bar_y1, bar_y2 = y1, y2
        bar_width = 6
        bar_height = bar_y2 - bar_y1
        
        # Detection confidence bar
        detection_height = int(bar_height * min(detection_score, 1.0))
        cv2.rectangle(frame, (bar_x, bar_y1), (bar_x + bar_width, bar_y2), (100, 100, 100), 1)
        cv2.rectangle(frame, (bar_x, bar_y2 - detection_height), (bar_x + bar_width, bar_y2), (255, 140, 0), -1)
        cv2.putText(frame, 'D', (bar_x - 2, bar_y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1)
        
        # Recognition confidence bar
        recognition_height = int(bar_height * min(recognition_score, 1.0))
        cv2.rectangle(frame, (bar_x + 12, bar_y1), (bar_x + 12 + bar_width, bar_y2), (100, 100, 100), 1)
        cv2.rectangle(frame, (bar_x + 12, bar_y2 - recognition_height), (bar_x + 12 + bar_width, bar_y2), color, -1)
        cv2.putText(frame, 'R', (bar_x + 10, bar_y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1)
        
        # Create info panel
        info_lines = []
        if person_info['type'] == 'employee':
            info_lines = [
                f"Name: {person_info['name']}",
                f"ID: {person_info['employeeId']}",
                f"Type: Employee",
                f"Score: {recognition_score:.2f}"
            ]
        elif person_info['type'] == 'visitor':
            info_lines = [
                f"Name: {person_info['name']}",
                f"Type: Visitor",
                f"Score: {recognition_score:.2f}"
            ]
        else:
            info_lines = [
                "Unknown Person",
                f"Detection: {detection_score:.2f}"
            ]
        
        # Calculate panel dimensions
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.45
        text_thickness = 1
        line_spacing = 18
        
        text_sizes = [cv2.getTextSize(line, font, font_scale, text_thickness)[0] for line in info_lines]
        panel_width = max(size[0] for size in text_sizes) + 20
        panel_height = len(info_lines) * line_spacing + 10
        
        # Position panel
        panel_x = max(0, min(x1, frame.shape[1] - panel_width))
        panel_y = max(0, y2 + 10)
        
        # Adjust if panel goes off screen
        if panel_y + panel_height > frame.shape[0]:
            panel_y = max(0, y1 - panel_height - 10)
        
        # Draw panel background
        panel_overlay = frame.copy()
        cv2.rectangle(panel_overlay, (panel_x, panel_y), 
                     (panel_x + panel_width, panel_y + panel_height), 
                     (30, 30, 30), -1)
        cv2.addWeighted(panel_overlay, 0.8, frame, 0.2, 0, frame)
        
        # Draw panel border
        cv2.rectangle(frame, (panel_x, panel_y), 
                     (panel_x + panel_width, panel_y + panel_height), 
                     color, 1)
        
        # Draw text
        for i, line in enumerate(info_lines):
            text_y = panel_y + 15 + i * line_spacing
            cv2.putText(frame, line, (panel_x + 10, text_y), 
                       font, font_scale, (255, 255, 255), text_thickness)
        
        return frame
        
    def recognize_faces(self, frame: np.ndarray, company_id: str) -> np.ndarray:
        """Recognize faces in the frame."""
        if self.face_detector is None:
            self.initialize_detector()
            
        # Get current embeddings for the company
        embeddings, metadata = self.embedding_manager.get_embeddings_for_company(company_id)
        
        if not embeddings:
            logger.warning(f"No embeddings found for company {company_id}")
            return frame
            
        try:
            faces = self.face_detector.get(frame)
            
            for face in faces:
                bbox = face.bbox.astype(int)
                face_embedding = face.normed_embedding / np.linalg.norm(face.normed_embedding)
                
                # Find best match
                best_match_id = None
                best_score = -1
                
                for person_id, registered_embedding in embeddings.items():
                    similarity = np.dot(face_embedding, registered_embedding)
                    if similarity > best_score:
                        best_score = similarity
                        best_match_id = person_id
                
                # Determine recognition result
                if best_match_id and best_score >= self.recognition_threshold:
                    person_info = metadata[best_match_id]
                    color = (0, 255, 0) if person_info['type'] == 'employee' else (0, 255, 255)
                    recognition_score = best_score
                else:
                    person_info = {'name': 'Unknown', 'type': 'unknown'}
                    color = (0, 0, 255)
                    recognition_score = 0
                
                # Draw bounding box with information
                frame = self.draw_enhanced_bounding_box(
                    frame, bbox, color, person_info, 
                    face.det_score, recognition_score
                )
                
        except Exception as e:
            logger.error(f"Error during face recognition: {e}")
            
        return frame

class CameraManager:
    """Manages multiple camera streams with multiprocessing."""
    
    def __init__(self, embedding_manager: EmbeddingManager):
        self.embedding_manager = embedding_manager
        self.running = False
        self.processes = []
        
    def capture_frames(self, source: int, frame_queue: mp.Queue):
        """Capture frames from camera source."""
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            logger.error(f"Failed to open camera {source}")
            return
            
        # Set camera properties for better performance
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        logger.info(f"Camera {source} initialized")
        
        while self.running:
            ret, frame = cap.read()
            if not ret:
                logger.warning(f"Failed to read frame from camera {source}")
                continue
                
            # Non-blocking put - skip frame if queue is full
            try:
                frame_queue.put_nowait(frame)
            except:
                pass  # Queue full, skip this frame
                
        cap.release()
        logger.info(f"Camera {source} released")
        
    def process_camera(self, source: int, frame_queue: mp.Queue, 
                      result_queue: mp.Queue, company_id: str):
        """Process frames from camera."""
        processor = FaceRecognitionProcessor(self.embedding_manager)
        
        while self.running:
            try:
                frame = frame_queue.get(timeout=1)
                processed_frame = processor.recognize_faces(frame, company_id)
                
                # Non-blocking put - skip frame if queue is full
                try:
                    result_queue.put_nowait((source, processed_frame))
                except:
                    pass  # Queue full, skip this frame
                    
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing camera {source}: {e}")
                
    def start_cameras(self, sources: List[int], company_id: str):
        """Start camera processing."""
        self.running = True
        
        # Create queues
        frame_queues = {source: mp.Queue(maxsize=2) for source in sources}
        result_queue = mp.Queue(maxsize=10)
        
        # Start capture processes
        for source in sources:
            p = mp.Process(target=self.capture_frames, 
                          args=(source, frame_queues[source]), 
                          daemon=True)
            p.start()
            self.processes.append(p)
            
        # Start processing processes
        for source in sources:
            p = mp.Process(target=self.process_camera, 
                          args=(source, frame_queues[source], result_queue, company_id), 
                          daemon=True)
            p.start()
            self.processes.append(p)
            
        # Display loop
        window_names = {source: f"Camera {source}" for source in sources}
        
        try:
            while self.running:
                try:
                    source, frame = result_queue.get(timeout=1)
                    cv2.imshow(window_names[source], frame)
                    
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                        
                except Empty:
                    continue
                    
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            
        finally:
            self.stop_cameras()
            
    def stop_cameras(self):
        """Stop all camera processes."""
        self.running = False
        cv2.destroyAllWindows()
        
        for process in self.processes:
            process.terminate()
            process.join(timeout=5)
            
        self.processes.clear()
        logger.info("All camera processes stopped")

# Flask API endpoints
embedding_manager = EmbeddingManager(Config.MONGODB_URI, Config.DATABASE_NAME)
camera_manager = CameraManager(embedding_manager)

@app.route('/api/embeddings/stats', methods=['GET'])
def get_embedding_stats():
    """Get embedding statistics."""
    return jsonify(embedding_manager.get_stats())

@app.route('/api/embeddings/sync', methods=['POST'])
def force_sync():
    """Force embedding synchronization."""
    try:
        embedding_manager.force_sync()
        return jsonify({'status': 'success', 'message': 'Sync completed'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/camera/start', methods=['POST'])
def start_camera():
    """Start camera recognition."""
    data = request.json
    sources = data.get('sources', [0])
    company_id = data.get('company_id')
    
    if not company_id:
        return jsonify({'status': 'error', 'message': 'Company ID required'}), 400
        
    try:
        # Start in a separate thread to avoid blocking
        Thread(target=camera_manager.start_cameras, 
               args=(sources, company_id), daemon=True).start()
        return jsonify({'status': 'success', 'message': 'Camera started'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/camera/stop', methods=['POST'])
def stop_camera():
    """Stop camera recognition."""
    try:
        camera_manager.stop_cameras()
        return jsonify({'status': 'success', 'message': 'Camera stopped'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info("Shutting down gracefully...")
    camera_manager.stop_cameras()
    embedding_manager.stop_sync()
    sys.exit(0)

if __name__ == "__main__":
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start embedding manager
    embedding_manager.start_sync()
    
    # Configuration
    video_sources = ["rtsp://admin:20021994@Om@192.168.1.28:554/Streaming/Channels/201"]
    video_sources = [0]
    company_id = "6827296ab6e06b08639107c4"
    
    try:
        # Start camera manager
        camera_manager.start_cameras(video_sources, company_id)
    except KeyboardInterrupt:
        logger.info("Application interrupted")
    finally:
        # Cleanup
        camera_manager.stop_cameras()
        embedding_manager.stop_sync()
        logger.info("Application shutdown complete")
