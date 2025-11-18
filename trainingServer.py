import time
import threading
import queue
import signal
import sys
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
import gc
import psutil
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from pymongo.collection import Collection
from datetime import datetime, timedelta
import cv2
import numpy as np
from insightface.app import FaceAnalysis
from bson import ObjectId
from gridfs import GridFS
import pickle

# Add parent directory to Python path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config.config import Config
from db import (
    employee_collection,
    visitor_collection,
    embedding_jobs_collection,
    employee_image_fs,
    employee_embedding_fs,
    visitor_image_fs,
    visitor_embedding_fs
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('face_embedding_worker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class JobStatus(Enum):
    QUEUED = "queued"
    STARTED = "started"
    DONE = "done"
    FAILED = "failed"
    DUPLICATE = "duplicate"

@dataclass
class WorkerConfig:
    model_name: str = "buffalo_l"
    worker_id: str = "buffalo_l_worker1"
    max_retries: int = 3
    heartbeat_interval: int = 10
    polling_interval: int = 2
    batch_size: int = 5
    max_workers: int = 3
    memory_threshold: float = 85.0  # Percentage
    cpu_threshold: float = 90.0     # Percentage
    timeout_minutes: int = 30
    similarity_threshold: float = 0.4
    duplicate_threshold: float = 0.4

class ResourceMonitor:
    """Monitor system resources to prevent overload."""
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.process = psutil.Process()
    
    def check_resources(self) -> bool:
        """Check if system has enough resources to process jobs."""
        try:
            memory_percent = psutil.virtual_memory().percent
            cpu_percent = psutil.cpu_percent(interval=1)
            
            if memory_percent > self.config.memory_threshold:
                logger.warning(f"Memory usage too high: {memory_percent}%")
                return False
            
            if cpu_percent > self.config.cpu_threshold:
                logger.warning(f"CPU usage too high: {cpu_percent}%")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error checking resources: {e}")
            return False
    
    def get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            return self.process.memory_info().rss / 1024 / 1024
        except Exception:
            return 0.0

class FaceEmbeddingWorker:
    """Optimized face embedding worker with resource management."""
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.resource_monitor = ResourceMonitor(config)
        self.face_detector = None
        self.shutdown_event = threading.Event()
        self.job_queue = queue.Queue(maxsize=config.batch_size * 2)
        self.executor = ThreadPoolExecutor(max_workers=config.max_workers)
        self.stats = {
            'processed': 0,
            'failed': 0,
            'duplicates': 0,
            'started_at': datetime.utcnow()
        }
        
        # Initialize face detector
        self._initialize_face_detector()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _initialize_face_detector(self):
        """Initialize face detector with proper error handling."""
        try:
            logger.info("Initializing face detector...")
            self.face_detector = FaceAnalysis(
                name=self.config.model_name,
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
            )
            self.face_detector.prepare(ctx_id=0)
            logger.info("Face detector initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize face detector: {e}")
            raise
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.shutdown_event.set()
    
    @contextmanager
    def _database_transaction(self, job_id: ObjectId):
        """Context manager for database transactions with proper error handling."""
        try:
            yield
        except Exception as e:
            logger.error(f"Database transaction failed for job {job_id}: {e}")
            # Mark job as failed
            try:
                embedding_jobs_collection.update_one(
                    {"_id": job_id},
                    {"$set": {
                        "status": JobStatus.FAILED.value,
                        "error": str(e),
                        "finishedAt": datetime.utcnow()
                    }}
                )
            except Exception as update_error:
                logger.error(f"Failed to update job status: {update_error}")
            raise
    
    def _check_duplicate_face(self, new_embedding: np.ndarray, company_id: ObjectId, 
                            collection: Collection, id_field: str) -> Tuple[bool, Optional[ObjectId]]:
        """Check if the face embedding is a duplicate."""
        try:
            cursor = collection.find({
                f'companyId': company_id,
                f'{id_field}Embeddings.buffalo_l.embeddingId': {'$exists': True}
            })
            
            embedding_fs = employee_embedding_fs if id_field == 'employee' else visitor_embedding_fs
            
            for doc in cursor:
                try:
                    emb_entry = doc[f'{id_field}Embeddings']['buffalo_l']
                    file = embedding_fs.get(emb_entry['embeddingId'])
                    existing_embedding = pickle.loads(file.read())
                    
                    if existing_embedding is not None:
                        sim = np.dot(new_embedding, existing_embedding) / (
                            np.linalg.norm(new_embedding) * np.linalg.norm(existing_embedding)
                        )
                        if sim > self.config.duplicate_threshold:
                            return True, doc[id_field]
                except Exception as e:
                    logger.warning(f"Error checking duplicate for doc {doc.get('_id')}: {e}")
                    continue
            
            return False, None
        except Exception as e:
            logger.error(f"Error in duplicate check: {e}")
            return False, None
    
    def _check_image_similarity(self, embeddings: List[np.ndarray]) -> Tuple[bool, Optional[Tuple[int, int]]]:
        """Check if all embeddings are of the same person."""
        if len(embeddings) < 2:
            return True, None
        
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                sim = np.dot(embeddings[i], embeddings[j]) / (
                    np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[j])
                )
                if sim < self.config.similarity_threshold:
                    return False, (i, j)
        return True, None
    
    def _process_image(self, image_id: ObjectId, image_fs: GridFS, position: str) -> Optional[np.ndarray]:
        """Process a single image and extract face embedding."""
        try:
            file = image_fs.get(image_id)
            file_bytes = np.frombuffer(file.read(), np.uint8)
            image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            
            if image is None:
                logger.warning(f"Failed to decode image {image_id}")
                return None
            
            faces = self.face_detector.get(image)
            logger.debug(f"{position}: {len(faces)} faces detected")
            
            if not faces:
                return None
            
            # If multiple faces, select the one with largest bounding box
            if len(faces) > 1:
                face_areas = [
                    (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])
                    for face in faces
                ]
                largest_face_idx = face_areas.index(max(face_areas))
                logger.debug(f"Multiple faces found in {position}, selecting largest face")
                return faces[largest_face_idx].normed_embedding
            else:
                return faces[0].normed_embedding
                
        except Exception as e:
            logger.error(f"Error processing {position} image {image_id}: {e}")
            return None
    
    def _process_job(self, job: Dict[str, Any]) -> bool:
        """Process a single embedding job."""
        job_id = job['_id']
        
        try:
            with self._database_transaction(job_id):
                # Determine job type
                is_visitor = 'visitorId' in job and job.get('visitorId') is not None
                doc_id = job.get('visitorId') if is_visitor else job.get('employeeId')
                
                if not doc_id:
                    raise ValueError("No ID found in job")
                
                # Ensure doc_id is ObjectId
                if isinstance(doc_id, str):
                    doc_id = ObjectId(doc_id)
                
                company_id = job['companyId']
                if isinstance(company_id, str):
                    company_id = ObjectId(company_id)
                
                # Set up collections and file systems
                collection = visitor_collection if is_visitor else employee_collection
                id_field = 'visitor' if is_visitor else 'employee'
                image_fs = visitor_image_fs if is_visitor else employee_image_fs
                embedding_fs = visitor_embedding_fs if is_visitor else employee_embedding_fs
                
                logger.info(f"Processing job for {doc_id} in {company_id} (type: {id_field})")
                
                # Update job status
                embedding_jobs_collection.update_one(
                    {"_id": job_id},
                    {"$set": {
                        "status": JobStatus.STARTED.value,
                        "startedAt": datetime.utcnow(),
                        "workerId": self.config.worker_id
                    }}
                )
                
                # Update document status
                collection.update_one(
                    {'companyId': company_id, '_id': doc_id},
                    {'$set': {
                        f'{id_field}Embeddings.buffalo_l.status': JobStatus.STARTED.value,
                        f'{id_field}Embeddings.buffalo_l.startedAt': datetime.utcnow()
                    }}
                )
                
                # Get document
                doc = collection.find_one({'companyId': company_id, '_id': doc_id})
                if doc is None:
                    raise ValueError(f"Document not found for {doc_id}")
                
                # Process images
                image_dict = doc.get(f'{id_field}Images', {})
                face_embeddings = []
                positions = ['left', 'right', 'center'] if is_visitor else ['center', 'left', 'right']
                
                for position in positions:
                    image_id = image_dict.get(position)
                    if not image_id:
                        continue
                    
                    embedding = self._process_image(ObjectId(image_id), image_fs, position)
                    if embedding is not None:
                        face_embeddings.append(embedding)
                    
                    # Update heartbeat
                    embedding_jobs_collection.update_one(
                        {"_id": job_id},
                        {"$set": {"heartbeat": datetime.utcnow()}}
                    )
                
                logger.info(f"Total faces found: {len(face_embeddings)}")
                
                if not face_embeddings:
                    raise ValueError("No faces found in any image")
                
                # Check if all faces are of the same person
                is_same_person, different_indices = self._check_image_similarity(face_embeddings)
                if not is_same_person:
                    i, j = different_indices
                    error_msg = f'Different persons detected in {positions[i]} and {positions[j]} images'
                    logger.warning(error_msg)
                    
                    collection.update_one(
                        {'companyId': company_id, '_id': doc_id},
                        {'$set': {
                            f'{id_field}Embeddings.buffalo_l.status': JobStatus.FAILED.value,
                            f'{id_field}Embeddings.buffalo_l.error': error_msg,
                            f'{id_field}Embeddings.buffalo_l.finishedAt': datetime.utcnow(),
                            'status': 'incomplete'
                        }}
                    )
                    
                    embedding_jobs_collection.update_one(
                        {"_id": job_id},
                        {"$set": {
                            "status": JobStatus.FAILED.value,
                            "error": error_msg,
                            "finishedAt": datetime.utcnow()
                        }}
                    )
                    return False
                
                # Calculate average embedding
                avg_embedding = np.mean(face_embeddings, axis=0)
                
                # Check for duplicates
                is_dup, dup_id = self._check_duplicate_face(avg_embedding, company_id, collection, id_field)
                if is_dup:
                    logger.info(f"Duplicate face found! {id_field}Id: {dup_id}")
                    
                    collection.update_one(
                        {'companyId': company_id, '_id': doc_id},
                        {'$set': {
                            f'{id_field}Embeddings.buffalo_l.status': JobStatus.DUPLICATE.value,
                            f'{id_field}Embeddings.buffalo_l.duplicateOf': dup_id,
                            f'{id_field}Embeddings.buffalo_l.finishedAt': datetime.utcnow(),
                            'status': 'pending_duplicate_removal'
                        }}
                    )
                    
                    embedding_jobs_collection.update_one(
                        {"_id": job_id},
                        {"$set": {
                            "status": JobStatus.DUPLICATE.value,
                            "finishedAt": datetime.utcnow()
                        }}
                    )
                    
                    self.stats['duplicates'] += 1
                    return True
                
                # Save embedding
                embedding_filename = f"{company_id}_{doc_id}_buffalo_l.pkl"
                embedding_metadata = {
                    'companyId': company_id,
                    f'{id_field}Id': doc_id,
                    'model': 'buffalo_l',
                    'type': 'embedding',
                    'timestamp': datetime.utcnow()
                }
                
                embedding_bytes = pickle.dumps(avg_embedding)
                embedding_id = embedding_fs.put(
                    embedding_bytes,
                    filename=embedding_filename,
                    metadata=embedding_metadata
                )
                
                # Update document
                emb_entry = {
                    'embeddingId': embedding_id,
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow(),
                    'status': JobStatus.DONE.value,
                    'finishedAt': datetime.utcnow(),
                    'corrupt': False
                }
                
                collection.update_one(
                    {'companyId': company_id, '_id': doc_id},
                    {'$set': {f'{id_field}Embeddings.buffalo_l': emb_entry}}
                )
                
                # Update job status
                embedding_jobs_collection.update_one(
                    {"_id": job_id},
                    {"$set": {
                        "status": JobStatus.DONE.value,
                        "finishedAt": datetime.utcnow()
                    }}
                )
                
                self.stats['processed'] += 1
                logger.info(f"Successfully processed job {job_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")
            self.stats['failed'] += 1
            
            # Handle retries
            retry_count = job.get('retryCount', 0) + 1
            if retry_count < self.config.max_retries:
                logger.info(f"Requeuing job {job_id} (retry {retry_count})")
                embedding_jobs_collection.update_one(
                    {"_id": job_id},
                    {"$set": {
                        "status": JobStatus.QUEUED.value,
                        "retryCount": retry_count,
                        "error": str(e),
                        "requeuedAt": datetime.utcnow()
                    }}
                )
            else:
                embedding_jobs_collection.update_one(
                    {"_id": job_id},
                    {"$set": {
                        "status": JobStatus.FAILED.value,
                        "error": str(e),
                        "finishedAt": datetime.utcnow()
                    }}
                )
            
            return False
    
    def _recover_stuck_jobs(self):
        """Recover jobs that are stuck in 'started' status."""
        try:
            now = datetime.utcnow()
            stuck_jobs = embedding_jobs_collection.find({
                "status": JobStatus.STARTED.value,
                "startedAt": {"$lt": now - timedelta(minutes=self.config.timeout_minutes)}
            })
            
            for job in stuck_jobs:
                retry_count = job.get('retryCount', 0) + 1
                if retry_count < self.config.max_retries:
                    logger.info(f"Requeuing stuck job: {job['_id']} (retry {retry_count})")
                    embedding_jobs_collection.update_one(
                        {"_id": job["_id"]},
                        {"$set": {
                            "status": JobStatus.QUEUED.value,
                            "retryCount": retry_count,
                            "requeuedAt": now
                        }}
                    )
                else:
                    logger.warning(f"Marking job as failed after max retries: {job['_id']}")
                    embedding_jobs_collection.update_one(
                        {"_id": job["_id"]},
                        {"$set": {
                            "status": JobStatus.FAILED.value,
                            "finishedAt": now,
                            "error": "Stuck too long after retries"
                        }}
                    )
        except Exception as e:
            logger.error(f"Error recovering stuck jobs: {e}")
    
    def _fetch_jobs(self) -> List[Dict[str, Any]]:
        """Fetch available jobs from the database."""
        try:
            jobs = list(embedding_jobs_collection.find(
                {"status": JobStatus.QUEUED.value, "model": self.config.model_name}
            ).sort("createdAt", 1).limit(self.config.batch_size))
            
            if jobs:
                # Mark jobs as started to prevent other workers from picking them up
                job_ids = [job['_id'] for job in jobs]
                embedding_jobs_collection.update_many(
                    {"_id": {"$in": job_ids}},
                    {"$set": {
                        "status": JobStatus.STARTED.value,
                        "startedAt": datetime.utcnow(),
                        "workerId": self.config.worker_id
                    }}
                )
            
            return jobs
        except Exception as e:
            logger.error(f"Error fetching jobs: {e}")
            return []
    
    def _cleanup_resources(self):
        """Clean up resources and force garbage collection."""
        try:
            gc.collect()
            memory_usage = self.resource_monitor.get_memory_usage()
            logger.debug(f"Memory usage after cleanup: {memory_usage:.2f} MB")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def _print_stats(self):
        """Print worker statistics."""
        uptime = datetime.utcnow() - self.stats['started_at']
        logger.info(f"Worker Stats - Processed: {self.stats['processed']}, "
                   f"Failed: {self.stats['failed']}, Duplicates: {self.stats['duplicates']}, "
                   f"Uptime: {uptime}")
    
    def run(self):
        """Main worker loop."""
        logger.info(f"Starting face embedding worker {self.config.worker_id}")
        
        last_recovery = time.time()
        last_stats = time.time()
        
        try:
            while not self.shutdown_event.is_set():
                try:
                    # Check system resources
                    if not self.resource_monitor.check_resources():
                        logger.warning("System resources low, waiting...")
                        time.sleep(self.config.polling_interval * 2)
                        continue
                    
                    # Recover stuck jobs periodically
                    if time.time() - last_recovery > 300:  # Every 5 minutes
                        self._recover_stuck_jobs()
                        last_recovery = time.time()
                    
                    # Print stats periodically
                    if time.time() - last_stats > 3600:  # Every hour
                        self._print_stats()
                        last_stats = time.time()
                    
                    # Fetch jobs
                    jobs = self._fetch_jobs()
                    
                    if not jobs:
                        logger.debug("No jobs found, waiting...")
                        time.sleep(self.config.polling_interval)
                        continue
                    
                    logger.info(f"Found {len(jobs)} jobs to process")
                    
                    # Process jobs concurrently
                    futures = []
                    for job in jobs:
                        future = self.executor.submit(self._process_job, job)
                        futures.append(future)
                    
                    # Wait for completion
                    for future in as_completed(futures):
                        try:
                            result = future.result()
                            if result:
                                logger.debug("Job completed successfully")
                        except Exception as e:
                            logger.error(f"Job failed: {e}")
                    
                    # Clean up resources after batch processing
                    self._cleanup_resources()
                    
                except KeyboardInterrupt:
                    logger.info("Received keyboard interrupt, shutting down...")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error in main loop: {e}")
                    time.sleep(self.config.polling_interval)
                    continue
                    
        except Exception as e:
            logger.error(f"Fatal error in worker: {e}")
        finally:
            # Cleanup
            logger.info("Shutting down worker...")
            self.executor.shutdown(wait=True)
            self._print_stats()
            logger.info("Worker shutdown complete")

def main():
    """Main function to start the worker."""
    config = WorkerConfig()
    worker = FaceEmbeddingWorker(config)
    worker.run()

if __name__ == "__main__":
    main()
