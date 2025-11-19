import cv2
import numpy as np
import pickle
from threading import Thread, Lock
import time
from datetime import datetime, timedelta
from insightface.app import FaceAnalysis
from pymongo import MongoClient, UpdateOne
from gridfs import GridFS
from bson import ObjectId
from flask import Flask, request, jsonify
from flask_cors import CORS
from app.config.config import Config
import logging
from typing import Dict, List, Optional, Tuple, Set
from enum import Enum
from collections import defaultdict, deque
import signal
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('campus_management.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

class CameraType(Enum):
    """Camera type enumeration."""
    ENTRY = "entry"
    EXIT = "exit"

class PersonStatus(Enum):
    """Person campus status."""
    INSIDE = "inside"
    OUTSIDE = "outside"

class EventType(Enum):
    """Event types."""
    ENTRY = "entry"
    EXIT = "exit"
    ANOMALY = "anomaly"


class UnknownPerson:
    """Track an unknown person with clustering."""
    
    def __init__(self, unknown_id: str, campus_id: str, first_timestamp: datetime,
                 first_camera: str, first_embedding: np.ndarray, first_bbox: List[int]):
        self.unknown_id = unknown_id
        self.campus_id = campus_id
        self.first_seen = first_timestamp
        self.last_seen = first_timestamp
        self.detection_count = 1
        self.cameras_seen = {first_camera}
        self.embeddings = deque(maxlen=10)
        self.embeddings.append(first_embedding)
        self.avg_embedding = first_embedding
        self.last_bbox = first_bbox
        
    def update(self, timestamp: datetime, camera_id: str, embedding: np.ndarray, bbox: List[int]):
        """Update unknown person with new detection."""
        self.last_seen = timestamp
        self.detection_count += 1
        self.cameras_seen.add(camera_id)
        self.embeddings.append(embedding)
        self.avg_embedding = np.mean(list(self.embeddings), axis=0)
        self.last_bbox = bbox
        
    def compute_similarity(self, embedding: np.ndarray) -> float:
        """Compute similarity with this unknown person."""
        return np.dot(self.avg_embedding, embedding)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'unknown_id': self.unknown_id,
            'campus_id': self.campus_id,
            'first_seen': self.first_seen,
            'last_seen': self.last_seen,
            'detection_count': self.detection_count,
            'cameras_seen': list(self.cameras_seen),
            'last_bbox': self.last_bbox
        }


class PersonState:
    """Represents the current state of a person."""
    
    def __init__(self, person_id: str, metadata: Dict, campus_id: str):
        self.person_id = person_id
        self.metadata = metadata
        self.campus_id = campus_id
        self.status = PersonStatus.OUTSIDE
        self.current_entry_time: Optional[datetime] = None
        self.last_exit_time: Optional[datetime] = None
        self.total_entries_today = 0
        self.total_exits_today = 0
        self.last_seen_camera: Optional[str] = None
        self.last_seen_time: Optional[datetime] = None
        
        # Pending detection tracking
        self.pending_entry_detection: Optional[datetime] = None
        self.pending_exit_detection: Optional[datetime] = None
        self.pending_entry_camera: Optional[str] = None
        self.pending_exit_camera: Optional[str] = None
        self.pending_entry_similarity: float = 0.0
        self.pending_exit_similarity: float = 0.0
        
        # Continuous monitoring
        self.detection_count_today = 0  # Total detections today
        self.last_detection_logged: Optional[datetime] = None  # Last time we logged a detection
        
    def should_log_detection(self, current_time: datetime, log_interval: float = 30.0) -> bool:
        """Check if we should log this detection (to avoid spam)."""
        if not self.last_detection_logged:
            return True
        time_since_last_log = (current_time - self.last_detection_logged).total_seconds()
        return time_since_last_log >= log_interval
        
    def start_entry_detection(self, camera_id: str, timestamp: datetime, similarity: float):
        """Start tracking an entry detection."""
        self.pending_entry_detection = timestamp
        self.pending_entry_camera = camera_id
        self.pending_entry_similarity = similarity
        
    def start_exit_detection(self, camera_id: str, timestamp: datetime, similarity: float):
        """Start tracking an exit detection."""
        self.pending_exit_detection = timestamp
        self.pending_exit_camera = camera_id
        self.pending_exit_similarity = similarity
        
    def confirm_entry(self, timestamp: datetime) -> bool:
        """Confirm entry if conditions are met."""
        if self.status == PersonStatus.OUTSIDE and self.pending_entry_detection:
            duration = (timestamp - self.pending_entry_detection).total_seconds()
            if duration >= 2.0:  # 2 second minimum
                self.status = PersonStatus.INSIDE
                self.current_entry_time = self.pending_entry_detection
                self.total_entries_today += 1
                self.last_seen_camera = self.pending_entry_camera
                self.last_seen_time = timestamp
                
                # Clear pending
                self.pending_entry_detection = None
                self.pending_entry_camera = None
                return True
        return False
    
    def confirm_exit(self, timestamp: datetime) -> bool:
        """Confirm exit if conditions are met."""
        if self.status == PersonStatus.INSIDE and self.pending_exit_detection:
            duration = (timestamp - self.pending_exit_detection).total_seconds()
            if duration >= 2.0:  # 2 second minimum
                self.status = PersonStatus.OUTSIDE
                self.last_exit_time = self.pending_exit_detection
                self.total_exits_today += 1
                self.last_seen_camera = self.pending_exit_camera
                self.last_seen_time = timestamp
                
                # Clear entry time
                self.current_entry_time = None
                self.pending_exit_detection = None
                self.pending_exit_camera = None
                return True
        return False
    
    def clear_stale_detections(self, current_time: datetime):
        """Clear pending detections if they're too old."""
        if self.pending_entry_detection:
            if (current_time - self.pending_entry_detection).total_seconds() > 5.0:
                self.pending_entry_detection = None
                self.pending_entry_camera = None
                
        if self.pending_exit_detection:
            if (current_time - self.pending_exit_detection).total_seconds() > 5.0:
                self.pending_exit_detection = None
                self.pending_exit_camera = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for database storage."""
        return {
            'person_id': self.person_id,
            'metadata': self.metadata,
            'campus_id': self.campus_id,
            'status': self.status.value,
            'current_entry_time': self.current_entry_time,
            'last_exit_time': self.last_exit_time,
            'total_entries_today': self.total_entries_today,
            'total_exits_today': self.total_exits_today,
            'last_seen_camera': self.last_seen_camera,
            'last_seen_time': self.last_seen_time,
            'detection_count_today': self.detection_count_today
        }


class CampusPeopleManager:
    """
    Optimized campus people management system.
    - Tracks people across multiple campuses
    - Batch database updates to minimize MongoDB load
    - Accurate entry/exit tracking with no duplicates
    """
    
    def __init__(self, mongodb_uri: str, database_name: str):
        self.client = MongoClient(mongodb_uri)
        self.db = self.client[database_name]
        
        # Collections
        self.people_status_collection = self.db['people_status']  # Current status of each person
        self.events_collection = self.db['campus_events']  # Historical events
        self.analytics_collection = self.db['campus_analytics']  # Aggregated analytics
        self.unknown_detections_collection = self.db['unknown_detections']  # Unknown people
        
        # Ensure indexes
        self._ensure_indexes()
        
        # Camera registry
        self.camera_configs = {}  # camera_id -> {campus_id, type, name}
        
        # In-memory state
        self.state_lock = Lock()
        self.people_states: Dict[str, PersonState] = {}  # person_id -> PersonState
        self.unknown_people: Dict[str, Dict[str, UnknownPerson]] = defaultdict(dict)  # campus_id -> {unknown_id: UnknownPerson}
        self.unknown_similarity_threshold = 0.65  # Cluster unknowns with > 0.65 similarity
        
        # Campus statistics (in-memory for fast access)
        self.campus_stats: Dict[str, Dict] = defaultdict(lambda: {
            'current_inside': 0,
            'employees_inside': set(),
            'visitors_inside': set(),
            'total_entries_today': 0,
            'total_exits_today': 0,
            'unknown_detections_today': 0,
            'unique_unknowns': 0  # Number of unique unknown people
        })
        
        # Batch update queue
        self.update_queue_lock = Lock()
        self.pending_updates: List[Dict] = []
        self.pending_events: List[Dict] = []
        self.batch_size = 50
        self.last_batch_time = time.time()
        self.batch_interval = 5  # Batch writes every 5 seconds
        
        # Load existing state
        self._load_people_state()
        
        # Start background threads
        self.running = True
        self.batch_thread = Thread(target=self._batch_update_loop, daemon=True)
        self.batch_thread.start()
        
        self.analytics_thread = Thread(target=self._analytics_loop, daemon=True)
        self.analytics_thread.start()
        
    def _ensure_indexes(self):
        """Create database indexes for performance."""
        try:
            self.people_status_collection.create_index([('person_id', 1), ('campus_id', 1)], unique=True)
            self.people_status_collection.create_index([('campus_id', 1), ('status', 1)])
            self.events_collection.create_index([('person_id', 1), ('timestamp', -1)])
            self.events_collection.create_index([('campus_id', 1), ('timestamp', -1)])
            self.events_collection.create_index([('event_type', 1), ('timestamp', -1)])
            self.analytics_collection.create_index([('campus_id', 1), ('date', -1)])
            self.unknown_detections_collection.create_index([('campus_id', 1), ('timestamp', -1)])
            logger.info("✅ Database indexes created")
        except Exception as e:
            logger.error(f"❌ Error creating indexes: {e}")
    
    def _load_people_state(self):
        """Load current people state from database."""
        try:
            cursor = self.people_status_collection.find({})
            
            with self.state_lock:
                for doc in cursor:
                    person_id = doc['person_id']
                    campus_id = doc['campus_id']
                    
                    state = PersonState(person_id, doc['metadata'], campus_id)
                    state.status = PersonStatus(doc['status'])
                    state.current_entry_time = doc.get('current_entry_time')
                    state.last_exit_time = doc.get('last_exit_time')
                    state.total_entries_today = doc.get('total_entries_today', 0)
                    state.total_exits_today = doc.get('total_exits_today', 0)
                    state.last_seen_camera = doc.get('last_seen_camera')
                    state.last_seen_time = doc.get('last_seen_time')
                    
                    self.people_states[person_id] = state
                    
                    # Update campus stats
                    if state.status == PersonStatus.INSIDE:
                        self.campus_stats[campus_id]['current_inside'] += 1
                        if state.metadata.get('type') == 'employee':
                            self.campus_stats[campus_id]['employees_inside'].add(person_id)
                        else:
                            self.campus_stats[campus_id]['visitors_inside'].add(person_id)
                    
                    self.campus_stats[campus_id]['total_entries_today'] += state.total_entries_today
                    self.campus_stats[campus_id]['total_exits_today'] += state.total_exits_today
            
            logger.info(f"✅ Loaded state for {len(self.people_states)} people")
            for campus_id, stats in self.campus_stats.items():
                logger.info(f"   📍 {campus_id}: {stats['current_inside']} inside")
                
        except Exception as e:
            logger.error(f"❌ Error loading people state: {e}")
    
    def register_camera(self, camera_id: str, campus_id: str, camera_type: CameraType, name: str = None):
        """Register a camera."""
        self.camera_configs[camera_id] = {
            'campus_id': campus_id,
            'type': camera_type,
            'name': name or camera_id
        }
        logger.info(f"📹 Registered: {camera_id} ({camera_type.value}) at campus '{campus_id}'")
    
    def process_detection(self, person_id: str, metadata: Dict, camera_id: str,
                         timestamp: datetime, similarity: float):
        """Process a recognized person detection."""
        camera_config = self.camera_configs.get(camera_id)
        if not camera_config:
            logger.warning(f"⚠️  Unknown camera: {camera_id}")
            return
        
        campus_id = camera_config['campus_id']
        camera_type = camera_config['type']
        
        with self.state_lock:
            # Get or create person state
            if person_id not in self.people_states:
                self.people_states[person_id] = PersonState(person_id, metadata, campus_id)
            
            state = self.people_states[person_id]
            
            # Update detection count and last seen
            state.detection_count_today += 1
            state.last_seen_camera = camera_id
            state.last_seen_time = timestamp
            
            # Log detection periodically (every 30 seconds)
            if state.should_log_detection(timestamp):
                logger.info(f"👁️  {metadata.get('name')} detected at {camera_id} "
                          f"(status: {state.status.value}, similarity: {similarity:.2f}, "
                          f"detections_today: {state.detection_count_today})")
                state.last_detection_logged = timestamp
            
            # Process based on camera type
            if camera_type == CameraType.ENTRY:
                self._handle_entry_detection(state, camera_id, timestamp, similarity)
            elif camera_type == CameraType.EXIT:
                self._handle_exit_detection(state, camera_id, timestamp, similarity)
    
    def _handle_entry_detection(self, state: PersonState, camera_id: str, 
                                timestamp: datetime, similarity: float):
        """Handle detection at entry camera."""
        # Only process if person is OUTSIDE
        if state.status == PersonStatus.OUTSIDE:
            # Start or continue tracking entry
            if not state.pending_entry_detection:
                state.start_entry_detection(camera_id, timestamp, similarity)
                logger.debug(f"👋 {state.metadata.get('name')} detected at entry, tracking...")
            else:
                # Check if enough time has passed to confirm
                if state.confirm_entry(timestamp):
                    campus_id = state.campus_id
                    
                    # Update stats
                    self.campus_stats[campus_id]['current_inside'] += 1
                    self.campus_stats[campus_id]['total_entries_today'] += 1
                    
                    if state.metadata.get('type') == 'employee':
                        self.campus_stats[campus_id]['employees_inside'].add(state.person_id)
                    else:
                        self.campus_stats[campus_id]['visitors_inside'].add(state.person_id)
                    
                    # Queue database update
                    self._queue_event(state.person_id, state.metadata, campus_id, camera_id,
                                    EventType.ENTRY, state.current_entry_time, similarity)
                    self._queue_state_update(state)
                    
                    logger.info(f"✅ ENTRY: {state.metadata.get('name')} entered {campus_id} "
                              f"(similarity: {similarity:.2f})")
        
        elif state.status == PersonStatus.INSIDE:
            # Person already inside - might be anomaly
            logger.debug(f"ℹ️  {state.metadata.get('name')} detected at entry but already inside")
    
    def _handle_exit_detection(self, state: PersonState, camera_id: str,
                               timestamp: datetime, similarity: float):
        """Handle detection at exit camera."""
        # Only process if person is INSIDE
        if state.status == PersonStatus.INSIDE:
            # Start or continue tracking exit
            if not state.pending_exit_detection:
                state.start_exit_detection(camera_id, timestamp, similarity)
                logger.debug(f"👋 {state.metadata.get('name')} detected at exit, tracking...")
            else:
                # Check if enough time has passed to confirm
                if state.confirm_exit(timestamp):
                    campus_id = state.campus_id
                    
                    # Update stats
                    self.campus_stats[campus_id]['current_inside'] -= 1
                    self.campus_stats[campus_id]['total_exits_today'] += 1
                    
                    if state.metadata.get('type') == 'employee':
                        self.campus_stats[campus_id]['employees_inside'].discard(state.person_id)
                    else:
                        self.campus_stats[campus_id]['visitors_inside'].discard(state.person_id)
                    
                    # Queue database update
                    self._queue_event(state.person_id, state.metadata, campus_id, camera_id,
                                    EventType.EXIT, state.last_exit_time, similarity)
                    self._queue_state_update(state)
                    
                    logger.info(f"✅ EXIT: {state.metadata.get('name')} exited {campus_id} "
                              f"(similarity: {similarity:.2f})")
        
        elif state.status == PersonStatus.OUTSIDE:
            # Person already outside - might be anomaly
            logger.debug(f"ℹ️  {state.metadata.get('name')} detected at exit but already outside")
    
    def process_unknown_detection(self, camera_id: str, timestamp: datetime, 
                                  face_embedding: np.ndarray, bbox: List[int]):
        """Process detection of unknown person with clustering."""
        camera_config = self.camera_configs.get(camera_id)
        if not camera_config:
            return
        
        campus_id = camera_config['campus_id']
        
        with self.state_lock:
            # Try to match with existing unknown people
            matched_unknown = None
            best_similarity = -1
            
            for unknown_id, unknown_person in self.unknown_people[campus_id].items():
                similarity = unknown_person.compute_similarity(face_embedding)
                if similarity > best_similarity:
                    best_similarity = similarity
                    if similarity >= self.unknown_similarity_threshold:
                        matched_unknown = unknown_person
                        break
            
            if matched_unknown:
                # Update existing unknown person
                matched_unknown.update(timestamp, camera_id, face_embedding, bbox)
                self.campus_stats[campus_id]['unknown_detections_today'] += 1
                
                # Log periodically (every 10 detections)
                if matched_unknown.detection_count % 10 == 0:
                    logger.warning(f"⚠️  Unknown person #{matched_unknown.unknown_id} detected again at {camera_id} "
                                 f"(total: {matched_unknown.detection_count} detections, "
                                 f"cameras: {len(matched_unknown.cameras_seen)})")
                
                # Queue update
                with self.update_queue_lock:
                    self.pending_events.append({
                        'type': 'unknown_detection',
                        'unknown_id': matched_unknown.unknown_id,
                        'campus_id': campus_id,
                        'camera_id': camera_id,
                        'timestamp': timestamp,
                        'bbox': [int(x) for x in bbox],
                        'detection_count': matched_unknown.detection_count
                    })
            else:
                # New unknown person
                unknown_id = f"unknown_{campus_id}_{len(self.unknown_people[campus_id]) + 1}"
                new_unknown = UnknownPerson(unknown_id, campus_id, timestamp, camera_id, 
                                           face_embedding, bbox)
                self.unknown_people[campus_id][unknown_id] = new_unknown
                
                # Update stats
                self.campus_stats[campus_id]['unknown_detections_today'] += 1
                self.campus_stats[campus_id]['unique_unknowns'] = len(self.unknown_people[campus_id])
                
                logger.warning(f"🆕 NEW unknown person detected: {unknown_id} at {camera_id} ({campus_id})")
                
                # Queue insert
                with self.update_queue_lock:
                    self.pending_events.append({
                        'type': 'unknown_detection',
                        'unknown_id': unknown_id,
                        'campus_id': campus_id,
                        'camera_id': camera_id,
                        'timestamp': timestamp,
                        'bbox': [int(x) for x in bbox],
                        'detection_count': 1,
                        'is_new': True
                    })
    
    def _queue_state_update(self, state: PersonState):
        """Queue a person state update for batch processing."""
        with self.update_queue_lock:
            self.pending_updates.append({
                'filter': {'person_id': state.person_id, 'campus_id': state.campus_id},
                'update': {'$set': state.to_dict()},
                'upsert': True
            })
    
    def _queue_event(self, person_id: str, metadata: Dict, campus_id: str, camera_id: str,
                    event_type: EventType, timestamp: datetime, similarity: float):
        """Queue an event for batch insertion."""
        with self.update_queue_lock:
            self.pending_events.append({
                'type': 'event',
                'person_id': person_id,
                'metadata': metadata,
                'campus_id': campus_id,
                'camera_id': camera_id,
                'event_type': event_type.value,
                'timestamp': timestamp,
                'similarity': float(similarity)
            })
    
    def _batch_update_loop(self):
        """Background thread to batch database updates."""
        while self.running:
            try:
                time.sleep(2)  # Check every 2 seconds
                
                current_time = time.time()
                should_flush = (current_time - self.last_batch_time) >= self.batch_interval
                
                with self.update_queue_lock:
                    has_updates = len(self.pending_updates) >= self.batch_size
                    has_events = len(self.pending_events) >= self.batch_size
                
                if should_flush or has_updates or has_events:
                    self._flush_updates()
                    self.last_batch_time = current_time
                    
            except Exception as e:
                logger.error(f"❌ Error in batch update loop: {e}")
                time.sleep(5)
    
    def _flush_updates(self):
        """Flush pending updates to database."""
        with self.update_queue_lock:
            updates_to_process = self.pending_updates[:]
            events_to_process = self.pending_events[:]
            self.pending_updates.clear()
            self.pending_events.clear()
        
        if not updates_to_process and not events_to_process:
            return
        
        try:
            # Batch update person states
            if updates_to_process:
                operations = [
                    UpdateOne(u['filter'], u['update'], upsert=u['upsert'])
                    for u in updates_to_process
                ]
                result = self.people_status_collection.bulk_write(operations, ordered=False)
                logger.debug(f"💾 Batch updated {result.modified_count} person states")
            
            # Batch insert events
            if events_to_process:
                regular_events = [e for e in events_to_process if e.get('type') == 'event']
                unknown_events = [e for e in events_to_process if e.get('type') == 'unknown_detection']
                
                if regular_events:
                    # Remove 'type' field before inserting
                    for e in regular_events:
                        e.pop('type', None)
                    self.events_collection.insert_many(regular_events, ordered=False)
                    logger.debug(f"💾 Batch inserted {len(regular_events)} events")
                
                if unknown_events:
                    for e in unknown_events:
                        e.pop('type', None)
                    self.unknown_detections_collection.insert_many(unknown_events, ordered=False)
                    logger.debug(f"💾 Batch inserted {len(unknown_events)} unknown detections")
                    
        except Exception as e:
            logger.error(f"❌ Error flushing batch updates: {e}")
    
    def _analytics_loop(self):
        """Background thread to update analytics periodically."""
        while self.running:
            try:
                time.sleep(60)  # Update every minute
                self._update_analytics()
            except Exception as e:
                logger.error(f"❌ Error in analytics loop: {e}")
                time.sleep(60)
    
    def _update_analytics(self):
        """Update aggregated analytics in database."""
        try:
            today = datetime.utcnow().date()
            
            for campus_id, stats in self.campus_stats.items():
                analytics_data = {
                    'campus_id': campus_id,
                    'date': datetime.combine(today, datetime.min.time()),
                    'current_inside': stats['current_inside'],
                    'employees_inside': len(stats['employees_inside']),
                    'visitors_inside': len(stats['visitors_inside']),
                    'total_entries': stats['total_entries_today'],
                    'total_exits': stats['total_exits_today'],
                    'unknown_detections': stats['unknown_detections_today'],
                    'timestamp': datetime.utcnow()
                }
                
                self.analytics_collection.update_one(
                    {'campus_id': campus_id, 'date': analytics_data['date']},
                    {'$set': analytics_data},
                    upsert=True
                )
            
            logger.debug("📊 Analytics updated")
            
        except Exception as e:
            logger.error(f"❌ Error updating analytics: {e}")
    
    def cleanup_stale_detections(self):
        """Clean up stale pending detections."""
        current_time = datetime.utcnow()
        
        with self.state_lock:
            for state in self.people_states.values():
                state.clear_stale_detections(current_time)
    
    def get_campus_status(self, campus_id: str = None) -> Dict:
        """Get current status for a campus or all campuses."""
        if campus_id:
            stats = self.campus_stats[campus_id]
            
            # Get unique unknowns count
            unique_unknowns = len(self.unknown_people.get(campus_id, {}))
            
            return {
                'campus_id': campus_id,
                'current_inside': stats['current_inside'],
                'employees_inside': len(stats['employees_inside']),
                'visitors_inside': len(stats['visitors_inside']),
                'total_entries_today': stats['total_entries_today'],
                'total_exits_today': stats['total_exits_today'],
                'unknown_detections_today': stats['unknown_detections_today'],
                'unique_unknowns_today': unique_unknowns
            }
        else:
            # Return all campuses
            result = {}
            for campus_id, stats in self.campus_stats.items():
                unique_unknowns = len(self.unknown_people.get(campus_id, {}))
                result[campus_id] = {
                    'campus_id': campus_id,
                    'current_inside': stats['current_inside'],
                    'employees_inside': len(stats['employees_inside']),
                    'visitors_inside': len(stats['visitors_inside']),
                    'total_entries_today': stats['total_entries_today'],
                    'total_exits_today': stats['total_exits_today'],
                    'unknown_detections_today': stats['unknown_detections_today'],
                    'unique_unknowns_today': unique_unknowns
                }
            return result
    
    def get_person_status(self, person_id: str) -> Optional[Dict]:
        """Get status of a specific person."""
        with self.state_lock:
            state = self.people_states.get(person_id)
            if state:
                return state.to_dict()
        return None
    
    def stop(self):
        """Stop the manager and flush pending updates."""
        logger.info("⏹️  Stopping campus people manager...")
        self.running = False
        
        # Flush any pending updates
        self._flush_updates()
        
        if self.batch_thread:
            self.batch_thread.join(timeout=5)
        if self.analytics_thread:
            self.analytics_thread.join(timeout=5)
            
        logger.info("✅ Campus people manager stopped")


class EmbeddingManager:
    """Manages face embeddings with periodic sync."""
    
    def __init__(self, mongodb_uri: str, database_name: str):
        self.client = MongoClient(mongodb_uri)
        self.db = self.client[database_name]
        self.employee_collection = self.db['employeeInfo']
        self.visitor_collection = self.db['visitors']
        self.employee_embedding_fs = GridFS(self.db, collection='employee_embeddings')
        self.visitor_embedding_fs = GridFS(self.db, collection='visitor_embeddings')
        
        self.embeddings_lock = Lock()
        self.embeddings: Dict[str, np.ndarray] = {}
        self.metadata: Dict[str, Dict] = {}
        
        self.sync_interval = 60  # Sync every minute
        self.running = False
        self.sync_thread = None
        
        self._initial_load()
    
    def _initial_load(self):
        """Load all embeddings."""
        try:
            logger.info("📥 Loading embeddings...")
            
            all_employees = self._get_all_active_employees()
            all_visitors = self._get_all_visitors()
            
            self._load_embeddings(all_employees, all_visitors)
            
            with self.embeddings_lock:
                employee_count = sum(1 for m in self.metadata.values() if m['type'] == 'employee')
                visitor_count = sum(1 for m in self.metadata.values() if m['type'] == 'visitor')
            
            logger.info(f"✅ Loaded {len(self.embeddings)} embeddings "
                       f"({employee_count} employees, {visitor_count} visitors)")
            
        except Exception as e:
            logger.error(f"❌ Error loading embeddings: {e}")
    
    def _get_all_active_employees(self) -> List[Dict]:
        """Get all active employees."""
        query = {
            'status': 'active',
            'blacklisted': False,
            'employeeEmbeddings.buffalo_l.status': 'done'
        }
        return list(self.employee_collection.find(query))
    
    def _get_all_visitors(self) -> List[Dict]:
        """Get all visitors."""
        query = {'visitorEmbeddings.buffalo_l.status': 'done'}
        return list(self.visitor_collection.find(query))
    
    def start_sync(self):
        """Start background sync."""
        if self.running:
            return
            
        self.running = True
        self.sync_thread = Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()
        logger.info("🔄 Embedding sync started")
    
    def stop_sync(self):
        """Stop background sync."""
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)
    
    def _sync_loop(self):
        """Background sync loop."""
        while self.running:
            try:
                time.sleep(self.sync_interval)
                all_employees = self._get_all_active_employees()
                all_visitors = self._get_all_visitors()
                self._load_embeddings(all_employees, all_visitors)
                logger.debug("🔄 Embeddings synced")
            except Exception as e:
                logger.error(f"❌ Error in sync loop: {e}")
    
    def _load_embeddings(self, employees: List[Dict], visitors: List[Dict]):
        """Load embeddings from database."""
        with self.embeddings_lock:
            for employee in employees:
                try:
                    emp_id = str(employee['_id'])
                    emb_entry = employee['employeeEmbeddings']['buffalo_l']
                    
                    file = self.employee_embedding_fs.get(emb_entry['embeddingId'])
                    embedding = pickle.loads(file.read())
                    normalized = embedding / np.linalg.norm(embedding)
                    
                    self.embeddings[emp_id] = normalized
                    self.metadata[emp_id] = {
                        'name': employee.get('employeeName', 'Unknown'),
                        'employeeId': employee.get('employeeId', 'Unknown'),
                        'type': 'employee'
                    }
                except Exception as e:
                    logger.error(f"❌ Error loading employee: {e}")
            
            for visitor in visitors:
                try:
                    visitor_id = str(visitor['_id'])
                    emb_entry = visitor['visitorEmbeddings']['buffalo_l']
                    
                    file = self.visitor_embedding_fs.get(ObjectId(emb_entry['embeddingId']))
                    embedding = pickle.loads(file.read())
                    normalized = embedding / np.linalg.norm(embedding)
                    
                    self.embeddings[visitor_id] = normalized
                    self.metadata[visitor_id] = {
                        'name': visitor.get('visitorName', 'Unknown'),
                        'type': 'visitor'
                    }
                except Exception as e:
                    logger.error(f"❌ Error loading visitor: {e}")
    
    def get_all(self) -> Tuple[Dict[str, np.ndarray], Dict[str, Dict]]:
        """Get all embeddings and metadata."""
        with self.embeddings_lock:
            return self.embeddings.copy(), self.metadata.copy()


class CameraProcessor:
    """Process camera feeds."""
    
    def __init__(self, embedding_manager: EmbeddingManager, manager: CampusPeopleManager):
        self.embedding_manager = embedding_manager
        self.manager = manager
        self.face_detector = None
        self.recognition_threshold = 0.45
        self.unknown_threshold = 0.35  # Below this = definitely unknown
        
    def initialize_detector(self):
        """Initialize face detector."""
        if self.face_detector is None:
            logger.info("🔧 Initializing face detector...")
            self.face_detector = FaceAnalysis(
                name="buffalo_l",
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
            )
            self.face_detector.prepare(ctx_id=0)
            logger.info("✅ Face detector initialized")
    
    def process_frame(self, frame: np.ndarray, camera_id: str) -> Dict:
        """Process a single frame. Returns detection statistics."""
        if self.face_detector is None:
            self.initialize_detector()
            
        embeddings, metadata = self.embedding_manager.get_all()
        
        if not embeddings:
            return {'faces': 0, 'recognized': 0, 'unknown': 0}
            
        timestamp = datetime.utcnow()
        stats = {'faces': 0, 'recognized': 0, 'unknown': 0}
        
        try:
            faces = self.face_detector.get(frame)
            stats['faces'] = len(faces)
            
            for face in faces:
                try:
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
                    
                    # Process if recognized
                    if best_match_id and best_score >= self.recognition_threshold:
                        person_info = metadata[best_match_id]
                        self.manager.process_detection(
                            best_match_id, person_info, camera_id, timestamp, float(best_score)
                        )
                        stats['recognized'] += 1
                    elif best_score < self.unknown_threshold:
                        # Definitely unknown person
                        self.manager.process_unknown_detection(
                            camera_id, timestamp, face_embedding, bbox.tolist()
                        )
                        stats['unknown'] += 1
                        
                except Exception as face_error:
                    logger.error(f"❌ Error processing face: {face_error}")
                    continue
            
        except Exception as e:
            logger.error(f"❌ Error in face detection: {e}")
            
        return stats


class CameraStreamManager:
    """Manage camera streams."""
    
    def __init__(self, embedding_manager: EmbeddingManager, manager: CampusPeopleManager):
        self.embedding_manager = embedding_manager
        self.manager = manager
        self.running = False
        self.camera_threads = {}
        
    def start_camera(self, camera_id: str, video_source, campus_id: str, 
                    camera_type: CameraType, name: str = None):
        """Start processing a camera."""
        if camera_id in self.camera_threads:
            logger.warning(f"⚠️  Camera {camera_id} already running")
            return
            
        self.manager.register_camera(camera_id, campus_id, camera_type, name)
        self.running = True
        
        thread = Thread(
            target=self._process_camera,
            args=(camera_id, video_source, camera_type),
            daemon=True
        )
        thread.start()
        self.camera_threads[camera_id] = thread
        logger.info(f"▶️  Started camera: {camera_id}")
    
    def _process_camera(self, camera_id: str, video_source, camera_type: CameraType):
        """Process camera stream in background thread."""
        processor = CameraProcessor(self.embedding_manager, self.manager)
        
        cap = cv2.VideoCapture(video_source)
        if not cap.isOpened():
            logger.error(f"❌ Failed to open camera {camera_id}: {video_source}")
            return
            
        logger.info(f"📹 Processing {camera_id} ({camera_type.value})")
        
        frame_skip = 2  # Process every 2nd frame
        frame_count = 0
        last_log_time = time.time()
        last_cleanup_time = time.time()
        log_interval = 30  # Log every 30 seconds
        cleanup_interval = 10  # Cleanup every 10 seconds
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        while self.running:
            try:
                ret, frame = cap.read()
                if not ret:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(f"❌ Too many errors on {camera_id}, stopping...")
                        break
                    logger.warning(f"⚠️  Failed to read from {camera_id}, retrying...")
                    time.sleep(1)
                    continue
                
                consecutive_errors = 0
                frame_count += 1
                
                if frame_count % frame_skip != 0:
                    continue
                    
                # Process frame
                try:
                    stats = processor.process_frame(frame, camera_id)
                except Exception as process_error:
                    logger.error(f"❌ Error processing frame: {process_error}")
                    continue
                
                # Periodic cleanup
                current_time = time.time()
                if current_time - last_cleanup_time >= cleanup_interval:
                    self.manager.cleanup_stale_detections()
                    last_cleanup_time = current_time
                
                # Periodic logging
                if current_time - last_log_time >= log_interval:
                    try:
                        camera_config = self.manager.camera_configs[camera_id]
                        campus_id = camera_config['campus_id']
                        campus_status = self.manager.get_campus_status(campus_id)
                        
                        logger.info(f"📊 {camera_id} | Frames: {frame_count} | "
                                  f"Campus: {campus_id} | Inside: {campus_status['current_inside']} | "
                                  f"Entries: {campus_status['total_entries_today']} | "
                                  f"Exits: {campus_status['total_exits_today']}")
                        last_log_time = current_time
                    except Exception as log_error:
                        logger.error(f"❌ Error logging: {log_error}")
                        last_log_time = current_time
                        
            except Exception as e:
                logger.error(f"❌ Unexpected error in camera loop: {e}", exc_info=True)
                time.sleep(1)
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    break
                    
        cap.release()
        logger.info(f"⏹️  Stopped camera: {camera_id}")
    
    def stop_all(self):
        """Stop all cameras."""
        logger.info("⏹️  Stopping all cameras...")
        self.running = False
        
        for camera_id, thread in self.camera_threads.items():
            thread.join(timeout=5)
            logger.info(f"✅ Stopped {camera_id}")
        
        self.camera_threads.clear()


# Flask API
app = Flask(__name__)
CORS(app)

embedding_manager = None
people_manager = None
camera_manager = None

def initialize_system():
    """Initialize the system."""
    global embedding_manager, people_manager, camera_manager
    
    logger.info("="*80)
    logger.info("🚀 INITIALIZING CAMPUS PEOPLE MANAGEMENT SYSTEM")
    logger.info("="*80)
    
    embedding_manager = EmbeddingManager(Config.MONGODB_URI, Config.DATABASE_NAME)
    people_manager = CampusPeopleManager(Config.MONGODB_URI, Config.DATABASE_NAME)
    camera_manager = CameraStreamManager(embedding_manager, people_manager)
    
    embedding_manager.start_sync()
    
    logger.info("✅ System initialized successfully")
    logger.info("="*80)


# API Endpoints

@app.route('/api/status', methods=['GET'])
def get_overall_status():
    """Get status of all campuses."""
    try:
        all_campuses = people_manager.get_campus_status()
        
        # Calculate totals
        total_inside = sum(c['current_inside'] for c in all_campuses.values())
        total_entries = sum(c['total_entries_today'] for c in all_campuses.values())
        total_exits = sum(c['total_exits_today'] for c in all_campuses.values())
        
        return jsonify({
            'success': True,
            'data': {
                'total_inside': total_inside,
                'total_entries_today': total_entries,
                'total_exits_today': total_exits,
                'campuses': all_campuses,
                'timestamp': datetime.utcnow().isoformat()
            }
        })
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/campus/<campus_id>/status', methods=['GET'])
def get_campus_status(campus_id):
    """Get status of specific campus."""
    try:
        status = people_manager.get_campus_status(campus_id)
        return jsonify({'success': True, 'data': status})
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/person/<person_id>', methods=['GET'])
def get_person(person_id):
    """Get person status."""
    try:
        person_status = people_manager.get_person_status(person_id)
        if person_status:
            return jsonify({'success': True, 'data': person_status})
        else:
            return jsonify({'success': False, 'error': 'Person not found'}), 404
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/campus/<campus_id>/events', methods=['GET'])
def get_campus_events(campus_id):
    """Get recent events for a campus."""
    try:
        limit = int(request.args.get('limit', 50))
        event_type = request.args.get('type')  # 'entry', 'exit', or None for all
        
        query = {'campus_id': campus_id}
        if event_type:
            query['event_type'] = event_type
            
        events = list(people_manager.events_collection.find(query)
                     .sort('timestamp', -1)
                     .limit(limit))
        
        # Convert ObjectId to string
        for event in events:
            event['_id'] = str(event['_id'])
            
        return jsonify({'success': True, 'data': events, 'count': len(events)})
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/campus/<campus_id>/people', methods=['GET'])
def get_campus_people(campus_id):
    """Get list of people currently inside a campus."""
    try:
        status_filter = request.args.get('status', 'inside')  # 'inside', 'outside', or 'all'
        
        query = {'campus_id': campus_id}
        if status_filter != 'all':
            query['status'] = status_filter
            
        people = list(people_manager.people_status_collection.find(query))
        
        # Convert ObjectId to string
        for person in people:
            person['_id'] = str(person['_id'])
            
        return jsonify({'success': True, 'data': people, 'count': len(people)})
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/campus/<campus_id>/analytics', methods=['GET'])
def get_campus_analytics(campus_id):
    """Get analytics for a campus over time."""
    try:
        days = int(request.args.get('days', 7))
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        analytics = list(people_manager.analytics_collection.find({
            'campus_id': campus_id,
            'date': {'$gte': start_date}
        }).sort('date', -1))
        
        # Convert ObjectId to string
        for record in analytics:
            record['_id'] = str(record['_id'])
            
        return jsonify({'success': True, 'data': analytics, 'count': len(analytics)})
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/campus/<campus_id>/unknown', methods=['GET'])
def get_unknown_detections(campus_id):
    """Get unique unknown people detected at a campus."""
    try:
        with people_manager.state_lock:
            unknown_people = people_manager.unknown_people.get(campus_id, {})
            
            result = []
            for unknown_id, unknown_person in unknown_people.items():
                result.append(unknown_person.to_dict())
        
        # Sort by detection count (most seen first)
        result.sort(key=lambda x: x['detection_count'], reverse=True)
        
        return jsonify({
            'success': True, 
            'data': result, 
            'total_unique': len(result),
            'total_detections': sum(u['detection_count'] for u in result)
        })
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/analytics/summary', methods=['GET'])
def get_analytics_summary():
    """Get summary analytics across all campuses."""
    try:
        all_campuses = people_manager.get_campus_status()
        
        summary = {
            'total_campuses': len(all_campuses),
            'total_inside': sum(c['current_inside'] for c in all_campuses.values()),
            'total_employees_inside': sum(c['employees_inside'] for c in all_campuses.values()),
            'total_visitors_inside': sum(c['visitors_inside'] for c in all_campuses.values()),
            'total_entries_today': sum(c['total_entries_today'] for c in all_campuses.values()),
            'total_exits_today': sum(c['total_exits_today'] for c in all_campuses.values()),
            'total_unknown_today': sum(c['unknown_detections_today'] for c in all_campuses.values()),
            'campus_breakdown': all_campuses,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify({'success': True, 'data': summary})
    except Exception as e:
        logger.error(f"❌ API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info("🛑 Shutdown signal received")
    if camera_manager:
        camera_manager.stop_all()
    if people_manager:
        people_manager.stop()
    if embedding_manager:
        embedding_manager.stop_sync()
    logger.info("👋 Goodbye!")
    sys.exit(0)


def print_status_loop():
    """Print status periodically in main thread."""
    last_print = time.time()
    print_interval = 60  # Print every 60 seconds
    
    while camera_manager and camera_manager.running:
        time.sleep(10)
        
        current_time = time.time()
        if current_time - last_print >= print_interval:
            all_campuses = people_manager.get_campus_status()
            
            logger.info("")
            logger.info("="*80)
            logger.info("📊 SYSTEM STATUS REPORT")
            logger.info("="*80)
            
            total_inside = 0
            total_entries = 0
            total_exits = 0
            
            for campus_id, stats in all_campuses.items():
                logger.info(f"")
                logger.info(f"📍 Campus: {campus_id}")
                logger.info(f"   ├─ Current Inside: {stats['current_inside']}")
                logger.info(f"   ├─ Employees: {stats['employees_inside']}")
                logger.info(f"   ├─ Visitors: {stats['visitors_inside']}")
                logger.info(f"   ├─ Entries Today: {stats['total_entries_today']}")
                logger.info(f"   ├─ Exits Today: {stats['total_exits_today']}")
                logger.info(f"   ├─ Unknown Detections: {stats['unknown_detections_today']}")
                logger.info(f"   └─ Unique Unknown People: {stats['unique_unknowns_today']}")
                
                total_inside += stats['current_inside']
                total_entries += stats['total_entries_today']
                total_exits += stats['total_exits_today']
            
            logger.info(f"")
            logger.info(f"🌐 Overall Totals:")
            logger.info(f"   ├─ Total Inside: {total_inside}")
            logger.info(f"   ├─ Total Entries: {total_entries}")
            logger.info(f"   └─ Total Exits: {total_exits}")
            logger.info("="*80)
            logger.info("")
            
            last_print = current_time


if __name__ == "__main__":
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize system
    initialize_system()
    
    # Camera configuration
    cameras = [
        {
            'camera_id': 'campus_a_entry_1',
            'video_source': 0,  # Change to RTSP URL for real cameras
            'campus_id': 'campus_a',
            'camera_type': CameraType.ENTRY,
            'name': 'Main Entry Gate'
        },
        # Add more cameras:
        # {
        #     'camera_id': 'campus_a_exit_1',
        #     'video_source': 'rtsp://192.168.1.100/stream',
        #     'campus_id': 'campus_a',
        #     'camera_type': CameraType.EXIT,
        #     'name': 'Main Exit Gate'
        # },
        # {
        #     'camera_id': 'campus_b_entry_1',
        #     'video_source': 'rtsp://192.168.1.101/stream',
        #     'campus_id': 'campus_b',
        #     'camera_type': CameraType.ENTRY,
        #     'name': 'Campus B Entry'
        # },
    ]
    
    # Start all cameras
    for cam in cameras:
        camera_manager.start_camera(
            cam['camera_id'],
            cam['video_source'],
            cam['campus_id'],
            cam['camera_type'],
            cam.get('name')
        )
    
    logger.info("")
    logger.info("="*80)
    logger.info("✅ CAMPUS PEOPLE MANAGEMENT SYSTEM RUNNING")
    logger.info("="*80)
    logger.info("📹 Cameras processing in background")
    logger.info("📊 Status updates every 60 seconds")
    logger.info("💾 Database updates batched every 5 seconds")
    logger.info("🛑 Press Ctrl+C to stop")
    logger.info("")
    logger.info("📡 API Endpoints:")
    logger.info("   GET /api/status - Overall status")
    logger.info("   GET /api/campus/<id>/status - Campus status")
    logger.info("   GET /api/campus/<id>/events - Campus events")
    logger.info("   GET /api/campus/<id>/people - People in campus")
    logger.info("   GET /api/campus/<id>/analytics - Analytics over time")
    logger.info("   GET /api/campus/<id>/unknown - Unknown detections")
    logger.info("   GET /api/person/<id> - Person status")
    logger.info("   GET /api/analytics/summary - Overall summary")
    logger.info("="*80)
    logger.info("")
    
    # Main thread: Print status periodically
    try:
        print_status_loop()
    except KeyboardInterrupt:
        logger.info("🛑 Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Error in main loop: {e}", exc_info=True)
    finally:
        signal_handler(None, None)
