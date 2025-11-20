"""
Kafka consumer that processes financial documents through LLM inference.

This service consumes documents from Kafka, processes them via vLLM,
and publishes results to an output topic.
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from typing import Dict, Optional
import re

import requests
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('kafka_llm_processor.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Import audit logger (optional - only if available)
try:
    from audit_logger import AuditLogger
    AUDIT_LOGGING_AVAILABLE = True
except ImportError:
    AUDIT_LOGGING_AVAILABLE = False
    logger.warning("Audit logging not available. Install dependencies.")

# Import drift detector (optional - only if available)
try:
    from drift_detector import DriftDetector, DriftMonitor
    DRIFT_DETECTION_AVAILABLE = True
except ImportError:
    DRIFT_DETECTION_AVAILABLE = False
    logger.warning("Drift detection not available. Install scipy for full functionality.")


class LLMProcessor:
    """Handles LLM inference requests."""
    
    def __init__(self, llm_url: str, model_name: str, timeout: int = 30, 
                 default_max_tokens: int = 200, default_temperature: float = 0.7):
        self.llm_url = llm_url
        self.model_name = model_name
        self.timeout = timeout
        self.default_max_tokens = default_max_tokens
        self.default_temperature = default_temperature
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        
    def process_document(self, document_text: str, max_tokens: int = None, retries: int = 1, 
                        temperature: float = None) -> Optional[Dict]:
        """
        Process a document through LLM inference.
        Supports both OpenAI-compatible API and Ollama API.
        
        Args:
            document_text: The text content to process
            max_tokens: Maximum tokens in response (default: from config or 200)
            retries: Number of retries on timeout (default: 1)
            temperature: Temperature for generation (default: from config or 0.7)
            
        Returns:
            LLM response dict or None if error
        """
        prompt = f"Extract key information from the following financial document:\n\n{document_text}"
        
        # Use defaults from config if not provided
        if max_tokens is None:
            max_tokens = getattr(self, 'default_max_tokens', 200)
        if temperature is None:
            temperature = getattr(self, 'default_temperature', 0.7)
        
        # Use Ollama API (default) or OpenAI-compatible API
        # Check if URL contains ollama port (11434) or use OpenAI-compatible
        use_ollama = '11434' in self.llm_url or 'ollama' in self.llm_url.lower()
        
        if not use_ollama:
            # Try OpenAI-compatible API first (vLLM, OpenAI, etc.)
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": 0.9
            }
            
            try:
                response = self.session.post(
                    f"{self.llm_url}/v1/completions",
                    json=payload,
                    timeout=self.timeout
                )
                response.raise_for_status()
                result = response.json()
                return result
            except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as e:
                logger.warning(f"OpenAI-compatible API failed, trying Ollama: {e}")
                use_ollama = True
        
        if use_ollama:
            # Use Ollama API format with retry logic
            for attempt in range(retries + 1):
                try:
                    ollama_payload = {
                        "model": self.model_name,
                        "prompt": prompt,
                        "stream": False,  # Disable streaming to get single JSON response
                        "options": {
                            "temperature": temperature,
                            "top_p": 0.9,
                            "num_predict": max_tokens
                        }
                    }
                    
                    if attempt > 0:
                        logger.info(f"Retrying LLM request (attempt {attempt + 1}/{retries + 1})")
                    
                    response = self.session.post(
                        f"{self.llm_url}/api/generate",
                        json=ollama_payload,
                        timeout=self.timeout
                    )
                    response.raise_for_status()
                    break  # Success, exit retry loop
                except requests.exceptions.Timeout:
                    if attempt < retries:
                        logger.warning(f"LLM request timeout (attempt {attempt + 1}), retrying...")
                        continue
                    else:
                        logger.error(f"LLM request timeout after {retries + 1} attempts")
                        return None
                except requests.exceptions.RequestException as e:
                    if attempt < retries:
                        logger.warning(f"LLM request failed (attempt {attempt + 1}): {e}, retrying...")
                        continue
                    else:
                        logger.error(f"LLM request failed after {retries + 1} attempts: {e}")
                        return None
            
            # Parse response (only reached if request succeeded)
            try:
                
                # Parse JSON response
                # Ollama returns single JSON object when stream=False
                try:
                    result = response.json()
                except json.JSONDecodeError as e:
                    # Handle case where response might have extra data
                    response_text = response.text.strip()
                    # Try to parse just the JSON part
                    if '\n' in response_text:
                        # Multiple lines - take the last complete JSON
                        lines = [l.strip() for l in response_text.split('\n') if l.strip()]
                        result = None
                        for line in reversed(lines):
                            try:
                                result = json.loads(line)
                                if isinstance(result, dict) and 'response' in result:
                                    break
                            except json.JSONDecodeError:
                                continue
                        if result is None:
                            raise json.JSONDecodeError("No valid JSON found", response_text, 0)
                    else:
                        # Single line - try to extract JSON
                        # Remove any trailing non-JSON text
                        try:
                            result = json.loads(response_text)
                        except json.JSONDecodeError:
                            # Try to find JSON object boundaries
                            start = response_text.find('{')
                            end = response_text.rfind('}') + 1
                            if start >= 0 and end > start:
                                result = json.loads(response_text[start:end])
                            else:
                                raise
                
                # Convert Ollama format to OpenAI-compatible
                return {
                    "choices": [{
                        "text": result.get('response', ''),
                        "index": 0,
                        "finish_reason": "stop" if result.get('done') else "length"
                    }],
                    "usage": {
                        "prompt_tokens": result.get('prompt_eval_count', len(prompt.split())),
                        "completion_tokens": result.get('eval_count', len(result.get('response', '').split())),
                        "total_tokens": result.get('prompt_eval_count', 0) + result.get('eval_count', 0)
                    }
                }
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing error: {e}")
                if 'response' in locals():
                    logger.error(f"Response text (first 500 chars): {response.text[:500]}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error in LLM processing: {e}", exc_info=True)
                return None


class KafkaLLMProcessor:
    """Main processor that consumes from Kafka and processes via LLM."""
    
    def __init__(self, config: Dict):
        self.config = config
        self.running = True
        self.processed_count = 0
        self.error_count = 0
        
        # Initialize LLM processor
        self.llm_processor = LLMProcessor(
            llm_url=config['llm_url'],
            model_name=config['model_name'],
            timeout=config.get('llm_timeout', 30),
            default_max_tokens=config.get('llm_max_tokens', 200),
            default_temperature=config.get('llm_temperature', 0.7)
        )
        
        # Initialize Kafka consumer
        self.consumer = KafkaConsumer(
            config['input_topic'],
            bootstrap_servers=config['kafka_brokers'],
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            key_deserializer=lambda k: k.decode('utf-8') if k else None,
            group_id=config.get('consumer_group', 'llm-processor-group'),
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            auto_commit_interval_ms=5000,
            max_poll_records=10,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000
        )
        
        # Initialize Kafka producer
        self.producer = KafkaProducer(
            bootstrap_servers=config['kafka_brokers'],
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            acks='all',
            retries=3,
            max_in_flight_requests_per_connection=1,
            compression_type='gzip',
            linger_ms=10,
            batch_size=16384
        )
        
        # Initialize audit logger if available
        self.audit_logger = None
        if AUDIT_LOGGING_AVAILABLE and config.get('enable_audit_logging', True):
            try:
                db_path = config.get('audit_db_path', os.getenv('AUDIT_DB_PATH', 'audit_logs.db'))
                self.audit_logger = AuditLogger(db_path=db_path)
                logger.info(f"Audit logging enabled: {db_path}")
            except Exception as e:
                logger.warning(f"Failed to initialize audit logger: {e}")
        
        # Initialize drift detector if available
        self.drift_monitor = None
        if DRIFT_DETECTION_AVAILABLE and config.get('enable_drift_detection', True):
            try:
                detector = DriftDetector(
                    baseline_window_size=config.get('drift_baseline_window', 100),
                    detection_window_size=config.get('drift_detection_window', 50),
                    drift_threshold=config.get('drift_threshold', 0.05),
                    min_samples=config.get('drift_min_samples', 20)
                )
                
                db_path = config.get('drift_db_path', os.getenv('DRIFT_DB_PATH', 'drift_alerts.db'))
                
                # Alert callback for logging
                def drift_alert_callback(drift_result):
                    logger.warning(
                        f"DRIFT DETECTED: score={drift_result['drift_score']:.3f}, "
                        f"features={drift_result['drifted_features']}"
                    )
                
                self.drift_monitor = DriftMonitor(
                    detector=detector,
                    db_path=db_path,
                    alert_callback=drift_alert_callback
                )
                logger.info(f"Drift detection enabled: {db_path}")
            except Exception as e:
                logger.warning(f"Failed to initialize drift detector: {e}")
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        
    def _create_result_message(self, original_message: Dict, llm_response: Dict, 
                              processing_time_ms: float) -> Dict:
        """Create structured result message."""
        return {
            'request_id': original_message.get('request_id', f"req_{int(time.time() * 1000)}"),
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'source': original_message.get('source', 'unknown'),
            'original_text': original_message.get('text', ''),
            'llm_response': llm_response.get('choices', [{}])[0].get('text', '') if llm_response else None,
            'model_used': self.config['model_name'],
            'processing_time_ms': round(processing_time_ms, 2),
            'tokens_used': llm_response.get('usage', {}).get('total_tokens', 0) if llm_response else 0,
            'status': 'success' if llm_response else 'error'
        }
        
    def process_message(self, message) -> bool:
        """
        Process a single Kafka message.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            document = message.value
            message_key = message.key
            
            if not document or 'text' not in document:
                logger.warning(f"Invalid message format: {document}")
                self.error_count += 1
                return False
                
            document_text = document['text']
            logger.info(f"Processing document from source: {document.get('source', 'unknown')}")
            
            # Process through LLM
            start_time = time.time()
            llm_response = self.llm_processor.process_document(
                document_text,
                max_tokens=self.config.get('llm_max_tokens', 200),
                temperature=self.config.get('llm_temperature', 0.7)
            )
            processing_time = (time.time() - start_time) * 1000
            
            # Create result message
            result_message = self._create_result_message(
                document,
                llm_response,
                processing_time
            )
            
            # Check for drift if LLM response successful
            if self.drift_monitor and llm_response:
                try:
                    drift_output = {
                        'text': result_message.get('llm_response', ''),
                        'tokens_used': result_message.get('tokens_used', 0),
                        'processing_time_ms': processing_time
                    }
                    
                    drift_result = self.drift_monitor.add_output(drift_output)
                    
                    if drift_result:
                        # Add drift alert to result message
                        result_message['drift_alert'] = {
                            'drift_detected': True,
                            'drift_score': drift_result['drift_score'],
                            'drifted_features': drift_result['drifted_features']
                        }
                        logger.warning(
                            f"Drift detected for request {result_message['request_id']}: "
                            f"score={drift_result['drift_score']:.3f}"
                        )
                except Exception as e:
                    logger.warning(f"Error in drift detection: {e}")
            
            # Log to audit trail
            if self.audit_logger:
                try:
                    audit_metadata = {
                        'request_id': result_message['request_id'],
                        'timestamp': result_message['timestamp'],
                        'model_version': self.config['model_name'],
                        'model_parameters': {
                            'temperature': self.config.get('llm_temperature', 0.7),
                            'max_tokens': self.config.get('llm_max_tokens', 200)
                        },
                        'processing_time_ms': processing_time,
                        'tenant_id': document.get('tenant_id'),
                        'user_id': document.get('user_id'),
                        'source': document.get('source', 'unknown')
                    }
                    
                    self.audit_logger.log_request(
                        input_text=document_text,
                        model_response=llm_response,
                        metadata=audit_metadata
                    )
                except Exception as e:
                    logger.warning(f"Failed to log audit entry: {e}")
            
            # Send to output topic
            future = self.producer.send(
                self.config['output_topic'],
                key=message_key,
                value=result_message
            )
            
            # Wait for send confirmation
            record_metadata = future.get(timeout=10)
            logger.info(
                f"Processed message: topic={record_metadata.topic}, "
                f"partition={record_metadata.partition}, offset={record_metadata.offset}, "
                f"time={processing_time:.2f}ms"
            )
            
            self.processed_count += 1
            return True
            
        except KafkaError as e:
            logger.error(f"Kafka error processing message: {e}")
            self.error_count += 1
            return False
        except Exception as e:
            logger.error(f"Unexpected error processing message: {e}", exc_info=True)
            self.error_count += 1
            return False
            
    def run(self):
        """Main processing loop."""
        logger.info("Starting Kafka LLM processor...")
        logger.info(f"Consuming from topic: {self.config['input_topic']}")
        logger.info(f"Publishing to topic: {self.config['output_topic']}")
        logger.info(f"LLM endpoint: {self.config['llm_url']}")
        
        try:
            while self.running:
                message_batch = self.consumer.poll(timeout_ms=1000, max_records=10)
                
                if not message_batch:
                    continue
                    
                for topic_partition, messages in message_batch.items():
                    for message in messages:
                        if not self.running:
                            break
                        self.process_message(message)
                        
                # Log stats periodically
                if self.processed_count % 100 == 0:
                    logger.info(
                        f"Stats: processed={self.processed_count}, "
                        f"errors={self.error_count}, "
                        f"success_rate={100 * (1 - self.error_count / max(self.processed_count, 1)):.1f}%"
                    )
                    
        except Exception as e:
            logger.error(f"Fatal error in processing loop: {e}", exc_info=True)
        finally:
            self.shutdown()
            
    def shutdown(self):
        """Gracefully shutdown the processor."""
        logger.info("Shutting down processor...")
        logger.info(f"Final stats: processed={self.processed_count}, errors={self.error_count}")
        
        try:
            self.consumer.close()
            self.producer.flush(timeout=10)
            self.producer.close()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


def validate_config(config: Dict) -> None:
    """
    Validate configuration on startup.
    
    Raises:
        ValueError: If configuration is invalid
    """
    errors = []
    
    # Validate required fields
    required_fields = ['kafka_brokers', 'input_topic', 'output_topic', 'llm_url', 'model_name']
    for field in required_fields:
        if not config.get(field):
            errors.append(f"Required configuration '{field}' is missing or empty")
    
    # Validate Kafka brokers format
    if config.get('kafka_brokers'):
        for broker in config['kafka_brokers']:
            if not broker or ':' not in broker:
                errors.append(f"Invalid Kafka broker format: '{broker}'. Expected 'host:port'")
            else:
                parts = broker.split(':')
                if len(parts) != 2:
                    errors.append(f"Invalid Kafka broker format: '{broker}'. Expected 'host:port'")
                else:
                    try:
                        port = int(parts[1])
                        if port < 1 or port > 65535:
                            errors.append(f"Invalid port in Kafka broker '{broker}'. Port must be 1-65535")
                    except ValueError:
                        errors.append(f"Invalid port in Kafka broker '{broker}'. Port must be a number")
    
    # Validate LLM URL format
    if config.get('llm_url'):
        if not config['llm_url'].startswith(('http://', 'https://')):
            errors.append(f"Invalid LLM URL: '{config['llm_url']}'. Must start with http:// or https://")
    
    # Validate numeric ranges
    if config.get('llm_timeout') is not None:
        if config['llm_timeout'] < 1 or config['llm_timeout'] > 600:
            errors.append(f"LLM timeout must be between 1 and 600 seconds, got {config['llm_timeout']}")
    
    if config.get('llm_max_tokens') is not None:
        if config['llm_max_tokens'] < 1 or config['llm_max_tokens'] > 100000:
            errors.append(f"LLM max_tokens must be between 1 and 100000, got {config['llm_max_tokens']}")
    
    if config.get('llm_temperature') is not None:
        if config['llm_temperature'] < 0.0 or config['llm_temperature'] > 2.0:
            errors.append(f"LLM temperature must be between 0.0 and 2.0, got {config['llm_temperature']}")
    
    # Validate drift detection parameters
    if config.get('drift_threshold') is not None:
        if config['drift_threshold'] < 0.0 or config['drift_threshold'] > 1.0:
            errors.append(f"Drift threshold must be between 0.0 and 1.0, got {config['drift_threshold']}")
    
    if config.get('drift_baseline_window') is not None:
        if config['drift_baseline_window'] < 10:
            errors.append(f"Drift baseline window must be at least 10, got {config['drift_baseline_window']}")
    
    if config.get('drift_detection_window') is not None:
        if config['drift_detection_window'] < 10:
            errors.append(f"Drift detection window must be at least 10, got {config['drift_detection_window']}")
    
    if config.get('drift_min_samples') is not None:
        if config['drift_min_samples'] < 1:
            errors.append(f"Drift min_samples must be at least 1, got {config['drift_min_samples']}")
    
    # Validate topic names (not empty, no invalid characters)
    for topic_field in ['input_topic', 'output_topic']:
        if config.get(topic_field):
            topic = config[topic_field]
            if not re.match(r'^[a-zA-Z0-9._-]+$', topic):
                errors.append(f"Invalid topic name '{topic}'. Use only alphanumeric, dots, underscores, and hyphens")
    
    # Log warnings for optional but recommended settings
    if config.get('consumer_group') == 'llm-processor-group':
        logger.warning("Using default consumer group. Consider setting CONSUMER_GROUP env var for production.")
    
    # Raise error if any validation failed
    if errors:
        error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {err}" for err in errors)
        raise ValueError(error_msg)
    
    logger.info(" Configuration validation passed")




def load_config() -> Dict:
    """Load configuration from environment variables with defaults."""
    return {
        'kafka_brokers': os.getenv('KAFKA_BROKERS', 'localhost:9092').split(','),
        'input_topic': os.getenv('INPUT_TOPIC', 'financial-documents'),
        'output_topic': os.getenv('OUTPUT_TOPIC', 'llm-results'),
        'consumer_group': os.getenv('CONSUMER_GROUP', 'llm-processor-group'),
        'llm_url': os.getenv('LLM_URL', 'http://localhost:11434'),  # Ollama default port
        'model_name': os.getenv('MODEL_NAME', 'llama2'),  # Default Ollama model
        'llm_timeout': int(os.getenv('LLM_TIMEOUT', '120')),  # Longer timeout for CPU-based Ollama (2 minutes)
        'llm_max_tokens': int(os.getenv('LLM_MAX_TOKENS', '200')),
        'llm_temperature': float(os.getenv('LLM_TEMPERATURE', '0.7')),
        'enable_audit_logging': os.getenv('ENABLE_AUDIT_LOGGING', 'true').lower() == 'true',
        'audit_db_path': os.getenv('AUDIT_DB_PATH', 'audit_logs.db'),
        'enable_drift_detection': os.getenv('ENABLE_DRIFT_DETECTION', 'true').lower() == 'true',
        'drift_db_path': os.getenv('DRIFT_DB_PATH', 'drift_alerts.db'),
        'drift_baseline_window': int(os.getenv('DRIFT_BASELINE_WINDOW', '100')),
        'drift_detection_window': int(os.getenv('DRIFT_DETECTION_WINDOW', '50')),
        'drift_threshold': float(os.getenv('DRIFT_THRESHOLD', '0.05')),
        'drift_min_samples': int(os.getenv('DRIFT_MIN_SAMPLES', '20'))
    }


def main():
    """Main entry point."""
    config = load_config()
    validate_config(config)
    processor = KafkaLLMProcessor(config)
    
    try:
        processor.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

