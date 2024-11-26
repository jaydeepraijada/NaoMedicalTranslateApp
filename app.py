import os
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from utils.translator import translate_text, transcribe_audio, validate_medical_terms

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

# Initialize SocketIO with CORS support
socketio = SocketIO(app, 
                   async_mode='eventlet', 
                   cors_allowed_origins="*",
                   ping_timeout=60,
                   ping_interval=25)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('transcribe_audio')
async def handle_transcription(data):
    try:
        audio_data = data['audio']
        language = data['language']
        
        # Transcribe audio using Whisper
        transcription = await transcribe_audio(audio_data, language)
        
        if 'error' in transcription:
            emit('transcription_error', {
                'error': transcription['error'],
                'message': transcription['message']
            })
            return

        if transcription and transcription['text']:
            # Validate medical terminology
            validated = validate_medical_terms(transcription['text'])
            
            if 'error' in validated:
                emit('transcription_response', {
                    'success': True,
                    'text': transcription['text'],  # Use original text if validation fails
                    'detected_language': transcription['detected_language'],
                    'confidence': transcription['confidence'],
                    'validation_error': validated['message']
                })
            else:
                response_data = {
                    'success': True,
                    'text': validated.get('corrected_text', validated.get('text', transcription['text'])),
                    'detected_language': transcription['detected_language'],
                    'confidence': transcription['confidence'],
                    'medical_terms': validated.get('medical_terms_found', []),
                    'corrections': validated.get('corrections', []),
                    'warnings': validated.get('warnings', [])
                }
                
                # If there are corrections or warnings, send them to the client
                if validated.get('corrections') or validated.get('warnings'):
                    emit('medical_validation_info', {
                        'corrections': validated.get('corrections', []),
                        'warnings': validated.get('warnings', [])
                    })
                
                emit('transcription_response', response_data)
        else:
            emit('transcription_error', {
                'error': 'transcription_failed',
                'message': 'Failed to transcribe audio'
            })
    except Exception as e:
        emit('transcription_error', {
            'error': 'system_error',
            'message': str(e)
        })

@socketio.on('translate_message')
def handle_translation(data):
    try:
        text = data['text']
        source_lang = data['source_lang']
        target_lang = data['target_lang']
        
        # Validate medical terminology before translation
        validated = validate_medical_terms(text)
        
        # Use validated text if available, otherwise use original
        text_to_translate = validated.get('corrected_text', validated.get('text', text))
        
        # If there are medical term corrections, notify the client
        if validated.get('corrections') or validated.get('warnings'):
            emit('medical_validation_info', {
                'corrections': validated.get('corrections', []),
                'warnings': validated.get('warnings', [])
            })
        
        # Translate the validated text
        translation = translate_text(text_to_translate, source_lang, target_lang)
        
        if 'error' in translation:
            emit('translation_error', {
                'error': translation['error'],
                'message': translation['message']
            })
            return
        
        # Emit the translation back to the client
        response_data = {
            'original': text,
            'translated': translation['text'],
            'source_lang': translation['source_lang'],
            'target_lang': translation['target_lang'],
            'confidence': translation['confidence']
        }
        
        # Include medical validation information if available
        if translation.get('medical_validation'):
            response_data['medical_validation'] = translation['medical_validation']
        if translation.get('translated_validation'):
            response_data['translated_validation'] = translation['translated_validation']
        
        emit('translation_response', response_data)
        
    except Exception as e:
        emit('translation_error', {
            'error': 'system_error',
            'message': str(e)
        })

@socketio.on('connect')
def handle_connect():
    emit('connection_response', {'data': 'Connected'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')
