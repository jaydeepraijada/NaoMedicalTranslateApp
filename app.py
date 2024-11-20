import os
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from logging.handlers import RotatingFileHandler
import eventlet
eventlet.monkey_patch()

# Now import translator module and initialize OpenAI
from utils.translator import (
    translate_text,
    transcribe_audio,
    validate_medical_terms_parallel,
    calculate_term_confidence,
    expand_medical_abbreviation,
    init_openai
)

# Initialize OpenAI client after monkey patching
init_openai()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add file handler for persistent logging
if not os.path.exists('logs'):
    os.makedirs('logs')
file_handler = RotatingFileHandler('logs/app.log', maxBytes=10000, backupCount=3)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger.addHandler(file_handler)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# Configure CORS for both REST and WebSocket
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "allow_headers": ["Content-Type"],
        "methods": ["GET", "POST", "OPTIONS"]
    }
})

# Initialize SocketIO with async mode properly configured
socketio = SocketIO(
    app,
    async_mode='eventlet',
    async_handlers=True,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    logger=True,
    engineio_logger=True
)

# Initialize thread pool for parallel processing
thread_pool = ThreadPoolExecutor(max_workers=4)

@app.route('/')
def index():
    logger.debug("Serving index page")
    return render_template('index.html')

@socketio.on('transcribe_audio')
async def handle_transcription(data):
    try:
        logger.debug("Starting transcription request")
        audio_data = data['audio']
        language = data['language']
        
        # Enhanced error handling for audio data validation
        if not audio_data:
            raise ValueError("No audio data provided")
        
        if not isinstance(language, str):
            raise ValueError("Invalid language format")
        
        # Enhanced transcription with parallel medical term validation
        transcription = await transcribe_audio(audio_data, language)
        
        if 'error' in transcription:
            logger.error(f"Transcription error: {transcription['error']}")
            emit('transcription_error', {
                'error': transcription['error'],
                'message': transcription['message'],
                'type': 'transcription_error'
            })
            return
        
        if transcription and transcription['text']:
            # Parallel medical term validation
            medical_terms = await validate_medical_terms_parallel(transcription['text'])
            
            # Process medical terms and generate corrections/suggestions
            corrections = []
            suggestions = []
            warnings = []
            confidence_threshold = 0.8
            
            for term in medical_terms:
                if term['confidence'] < confidence_threshold:
                    warnings.append(f"Low confidence term detected: {term['term']}")
                
                if term.get('expanded'):
                    suggestions.append(f"{term['term']} → {term['expanded']}")
                
                # Add real-time correction suggestions
                if term['confidence'] > 0.9:
                    expanded = expand_medical_abbreviation(term['term'])
                    if expanded != term['term']:
                        corrections.append({
                            'original': term['term'],
                            'suggested': expanded,
                            'confidence': term['confidence']
                        })

            # Calculate overall voice input confidence
            voice_confidence = transcription.get('confidence', 0.7)
            medical_term_confidence = sum(t['confidence'] for t in medical_terms) / len(medical_terms) if medical_terms else 0.7
            overall_confidence = (voice_confidence + medical_term_confidence) / 2

            response_data = {
                'success': True,
                'text': transcription['text'],
                'detected_language': transcription['detected_language'],
                'confidence': overall_confidence,
                'medical_terms': medical_terms,
                'corrections': corrections,
                'suggestions': suggestions,
                'warnings': warnings
            }

            # Emit medical validation info separately for UI updates
            if corrections or warnings or suggestions:
                emit('medical_validation_info', {
                    'corrections': corrections,
                    'warnings': warnings,
                    'suggestions': suggestions
                })
            
            logger.info("Transcription completed successfully")
            emit('transcription_response', response_data)
        else:
            logger.error("Empty transcription result")
            emit('transcription_error', {
                'error': 'transcription_failed',
                'message': 'Failed to transcribe audio',
                'type': 'empty_result'
            })
            
    except ValueError as ve:
        logger.error(f"Validation error: {str(ve)}")
        emit('transcription_error', {
            'error': 'validation_error',
            'message': str(ve),
            'type': 'validation'
        })
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}", exc_info=True)
        emit('transcription_error', {
            'error': 'system_error',
            'message': "An unexpected error occurred during transcription",
            'type': 'system'
        })

@socketio.on('translate_message')
async def handle_translation(data):
    """
    Handle translation requests with enhanced error handling and logging
    """
    try:
        logger.debug(f"Starting translation request: {data}")
        
        # Input validation
        required_fields = ['text', 'source_lang', 'target_lang']
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        text = data['text']
        source_lang = data['source_lang']
        target_lang = data['target_lang']

        if not text.strip():
            raise ValueError("Empty text provided for translation")

        # Parallel medical term validation
        logger.debug("Starting medical term validation")
        medical_terms = await validate_medical_terms_parallel(text)
        
        # Process medical terms
        corrections = []
        warnings = []
        preserved_terms = {}
        
        for term in medical_terms:
            if term['confidence'] > 0.8:
                preserved_terms[term['term']] = term
                if term.get('expanded'):
                    corrections.append(f"Expanded: {term['term']} → {term['expanded']}")
            else:
                warnings.append(f"Uncertain medical term: {term['term']}")

        # Notify client of medical term processing
        if corrections or warnings:
            logger.debug("Sending medical validation info to client")
            emit('medical_validation_info', {
                'corrections': corrections,
                'warnings': warnings,
                'terms': [term for term in medical_terms if term['confidence'] > 0.7]
            })
        
        # Perform translation with proper await
        logger.info(f"Initiating translation from {source_lang} to {target_lang}")
        translation = await translate_text(text, source_lang, target_lang)
        
        if 'error' in translation:
            logger.error(f"Translation error: {translation.get('message', 'Unknown error')}")
            error_message = translation.get('message', 'Translation service error')
            service_status = ''
            
            if 'openai' in str(error_message).lower():
                service_status = 'Primary service (OpenAI) unavailable, switching to backup service...'
                emit('service_status', {
                    'status': 'switching',
                    'message': service_status
                })
            elif 'google' in str(error_message).lower():
                service_status = 'Backup service (Google Translate) also failed'
                emit('service_status', {
                    'status': 'failed',
                    'message': service_status
                })
            
            emit('translation_error', {
                'error': translation['error'],
                'message': error_message,
                'service_status': service_status,
                'details': translation.get('details', {}),
                'type': 'translation_error'
            })
            return
        
        # Enhance response with service information
        service_info = {
            'service_name': translation.get('service', 'unknown'),
            'confidence': translation.get('confidence', 0.0),
            'service_switch': translation.get('service_switch', None)
        }
        
        # Update response with all information
        translation.update({
            'medical_terms': medical_terms,
            'preserved_terms': list(preserved_terms.keys()),
            'corrections': corrections,
            'warnings': warnings,
            'service_info': service_info
        })
        
        # Emit service status update
        emit('service_status', {
            'status': 'success',
            'service': service_info['service_name'],
            'confidence': service_info['confidence']
        })
        
        logger.info(f"Translation completed successfully using {service_info['service_name']}")
        emit('translation_response', translation)
        
    except ValueError as ve:
        logger.warning(f"Validation error in translation request: {str(ve)}")
        emit('translation_error', {
            'error': 'validation_error',
            'message': str(ve),
            'service_status': 'Request validation failed',
            'type': 'validation'
        })
    except Exception as e:
        logger.error(f"Unexpected error in handle_translation: {str(e)}", exc_info=True)
        emit('translation_error', {
            'error': 'system_error',
            'message': "An unexpected error occurred. Please try again later.",
            'service_status': 'System error occurred',
            'type': 'system'
        })

@socketio.on('connect')
def handle_connect():
    logger.info("Client connected")
    emit('connection_response', {'data': 'Connected', 'status': 'success'})

@socketio.on('disconnect')
def handle_disconnect():
    logger.info("Client disconnected")

if __name__ == '__main__':
    logger.info("Starting Flask SocketIO server")
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))