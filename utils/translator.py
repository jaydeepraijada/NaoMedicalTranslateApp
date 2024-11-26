import os
import time
import functools
import asyncio
import json
import re
import logging
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from collections import deque
from datetime import datetime, timedelta
from googletrans import Translator
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenAI client with API key
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Circuit breaker configuration
class CircuitBreaker:
    def __init__(self, failure_threshold=5, reset_timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened due to {self.failure_count} failures")

    def record_success(self):
        self.failure_count = 0
        self.state = "closed"

    def can_execute(self):
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "half-open"
                return True
            return False
        return self.state == "half-open"

# Initialize circuit breakers
api_circuit_breaker = CircuitBreaker()
translation_circuit_breaker = CircuitBreaker()

# Response cache for translations and validations
CACHE_TIMEOUT = 3600  # 1 hour
response_cache = {}

# Extended Language code mapping
LANGUAGE_CODES = {
    'zh': ['zh-CN', 'zh-TW', 'zh-HK', 'cmn', 'zh'],  # Chinese variants
    'en': ['en-US', 'en-GB', 'en-AU', 'en'],
    'es': ['es-ES', 'es-MX', 'es-AR', 'es'],
    'fr': ['fr-FR', 'fr-CA', 'fr'],
    'de': ['de-DE', 'de-AT', 'de'],
    'hi': ['hi-IN', 'hi'],  # Hindi
    'ja': ['ja-JP', 'ja'],  # Japanese
    'ko': ['ko-KR', 'ko'],  # Korean
    'ru': ['ru-RU', 'ru'],  # Russian
    'ar': ['ar-SA', 'ar'],  # Arabic
    'pt': ['pt-BR', 'pt-PT', 'pt'],  # Portuguese
    'it': ['it-IT', 'it'],  # Italian
    'nl': ['nl-NL', 'nl'],  # Dutch
    'pl': ['pl-PL', 'pl'],  # Polish
    'tr': ['tr-TR', 'tr']   # Turkish
}

# Common medical term patterns
MEDICAL_PATTERNS = {
    'measurements': r'\d+\s*(mg|mcg|ml|g|kg|mmHg|°[CF])',
    'vital_signs': r'(BP|HR|RR|SpO2|Temp)[:\s]*\d+',
    'common_abbreviations': r'\b(IV|IM|SC|PO|PRN|bid|tid|qid|qd|hs)\b',
}

def normalize_language_code(lang_code):
    """
    Normalize language codes to a standard format
    """
    if not lang_code:
        return None
    
    lang_code = lang_code.lower()
    base_code = lang_code.split('-')[0]
    
    if base_code in LANGUAGE_CODES:
        return base_code
    
    for code, variants in LANGUAGE_CODES.items():
        if lang_code in [v.lower() for v in variants]:
            return code
    
    return None

async def transcribe_audio(audio_data, language="en"):
    """
    Transcribe audio using OpenAI Whisper API with focus on medical terminology
    """
    try:
        # Normalize language code
        norm_lang = normalize_language_code(language)
        if not norm_lang:
            raise ValueError(f"Unsupported language code: {language}")

        # Enhanced medical context prompt
        medical_prompt = """
        This is a specialized medical conversation requiring high accuracy. Please focus on:
        1. Medical Terminology:
           - Precise medical terms and diagnoses
           - Anatomical terminology
           - Disease names and conditions
           - Medical procedures and treatments
        2. Measurements and Dosages:
           - Drug dosages (mg, mcg, mL)
           - Vital signs (BP, HR, RR, SpO2)
           - Lab values and ranges
           - Temperature (°C/°F)
        3. Medical Abbreviations:
           - Standard medical abbreviations (PRN, BID, TID, QID)
           - Route abbreviations (PO, IV, IM, SC)
           - Common medical shorthand
        4. Multilingual Medical Context:
           - Standard medical terminology across languages
           - International drug names
           - Regional medical practices
        5. Critical Information:
           - Allergies and contraindications
           - Emergency terminology
           - Patient safety information
        """
        
        # Create audio file object for the API
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_data,
            language=norm_lang,
            prompt=medical_prompt,
            temperature=0.2  # Lower temperature for more accurate medical terms
        )
        
        if hasattr(response, 'text'):
            # Validate medical terms and calculate confidence
            validated = validate_medical_terms(response.text)
            
            # Calculate confidence based on medical term validation
            base_confidence = 0.85  # Base confidence for successful transcription
            medical_confidence = validated.get('confidence', 1.0) if isinstance(validated, dict) else 1.0
            
            # Adjust confidence based on medical term validation
            adjusted_confidence = base_confidence * medical_confidence
            
            return {
                'text': validated.get('corrected_text', response.text) if isinstance(validated, dict) else response.text,
                'language': norm_lang,
                'confidence': adjusted_confidence,
                'detected_language': norm_lang,
                'medical_validation': validated if isinstance(validated, dict) else None,
                'medical_terms_found': validated.get('medical_terms_found', []) if isinstance(validated, dict) else []
            }
        else:
            return {
                'text': str(response),
                'language': norm_lang,
                'confidence': 0.0,
                'detected_language': norm_lang
            }
    except ValueError as e:
        print(f"Language code error: {str(e)}")
        return {
            'error': 'invalid_language',
            'message': str(e)
        }
    except Exception as e:
        print(f"Whisper transcription error: {str(e)}")
        return {
            'error': 'transcription_failed',
            'message': str(e)
        }

def extract_medical_terms(text):
    """
    Extract potential medical terms from text using patterns
    """
    medical_terms = []
    
    # Extract terms matching medical patterns
    for pattern_name, pattern in MEDICAL_PATTERNS.items():
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            medical_terms.append({
                'term': match.group(),
                'type': pattern_name,
                'position': match.span()
            })
    
    # Extract potential drug names and medical conditions
    words = text.split()
    for word in words:
        # Look for capitalized words that might be drug names
        if word[0].isupper() and len(word) > 3:
            medical_terms.append({
                'term': word,
                'type': 'potential_drug_name',
                'position': (text.index(word), text.index(word) + len(word))
            })
    
    return medical_terms

async def validate_medical_terms(text):
    """
    Validate and correct medical terminology using pattern matching and OpenAI with optimizations
    """
    try:
        # Check cache first
        cache_key = generate_cache_key(text)
        if cached_result := get_cached_response(cache_key):
            logger.info(f"Cache hit for text validation: {cache_key[:50]}...")
            return cached_result

        # Circuit breaker check
        if not api_circuit_breaker.can_execute():
            logger.warning("Circuit breaker is open, using fallback validation")
            return {'text': text, 'confidence': 0.8, 'validated': True, 'circuit_breaker': 'open'}

        # First pass: Extract potential medical terms
        medical_terms = extract_medical_terms(text)
        
        # Early return for simple cases
        if not medical_terms:
            result = {'text': text, 'confidence': 1.0, 'validated': True}
            cache_response(cache_key, result)
            return result

        # Batch validate medical terms first
        terms_to_validate = [term['term'] for term in medical_terms]
        validated_terms = await batch_validate_medical_terms(terms_to_validate)

        # Early return for high-confidence terms
        high_confidence = all(
            term['term'] in validated_terms and 
            validated_terms[term['term']].get('confidence', 0) > 0.95 
            for term in medical_terms
        )
        if high_confidence:
            result = {
                'text': text,
                'confidence': 0.98,
                'validated': True,
                'medical_terms_found': medical_terms,
                'validation_method': 'high_confidence'
            }
            cache_response(cache_key, result)
            return result

        # Prepare the context for GPT with the identified terms and their validations
        context = f"""
        Please validate and correct the following text, paying special attention to medical terminology:
        {json.dumps([term['term'] for term in medical_terms], indent=2)}
        
        Pre-validated terms:
        {json.dumps(validated_terms, indent=2)}
        
        Rules for Medical Term Processing:
        1. Correct any misspelled medical terms (e.g., "penicillin", "allergic")
        2. Standardize medical abbreviations (e.g., "IV", "BP")
        3. Verify and correct dosage formats
        4. Flag any dangerous or concerning medical information
        5. Maintain the original meaning

        Rules for Non-Medical Term Detection:
        1. Identify general context words (e.g., "pizza", "favorite food")
        2. Separate medical context (e.g., "allergic", "penicillin") from general context
        3. Mark common everyday terms that aren't medical in nature
        4. Flag terms that might need medical clarification
        
        Original text: {text}
        
        Please respond with a JSON object containing:
        - corrected_text: the text with corrected medical terms
        - corrections: list of corrections made
        - warnings: list of any medical concerns
        - non_medical_terms: list of identified non-medical terms that aren't related to healthcare
        - medical_terms_found: list of valid medical terms identified
        - confidence: confidence score for the corrections (0.0 to 1.0)
        """
        
        try:
            # Implement retry mechanism with circuit breaker
            if not api_circuit_breaker.can_execute():
                raise Exception("Circuit breaker is open")

            response = await retry_api_call(
                client.chat.completions.create,
                model="gpt-4",
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a medical terminology expert. Validate and correct medical terms while preserving the original meaning. Return your response in a valid JSON format."
                    },
                    {"role": "user", "content": context}
                ],
                temperature=0.3,  # Increased for faster processing
                max_tokens=500
            )

            if response.choices[0].message.content:
                try:
                    result = json.loads(response.choices[0].message.content)
                    
                    # Record success for circuit breaker
                    api_circuit_breaker.record_success()
                    
                    # Add metadata about the validation process
                    result['original_text'] = text
                    result['medical_terms_found'] = medical_terms
                    result['validation_timestamp'] = datetime.now().isoformat()
                    result['processing_info'] = {
                        'cached_terms': len(validated_terms),
                        'total_terms': len(medical_terms),
                        'high_confidence': high_confidence
                    }
                    
                    # Cache the result
                    cache_response(cache_key, result)
                    return result
                    
                except json.JSONDecodeError as jde:
                    logger.error(f"JSON decode error: {str(jde)}")
                    # Fallback to basic validation
                    result = {
                        'corrected_text': response.choices[0].message.content,
                        'confidence': 0.7,
                        'validated': True,
                        'fallback': 'json_decode_error'
                    }
                    cache_response(cache_key, result)
                    return result
            else:
                api_circuit_breaker.record_failure()
                return {
                    'text': text,
                    'confidence': 0.5,
                    'validated': False,
                    'message': 'Validation produced no results',
                    'fallback': 'empty_response'
                }
                
        except Exception as e:
            logger.error(f"Medical term validation error: {str(e)}", exc_info=True)
            api_circuit_breaker.record_failure()
            
            # Implement fallback mechanism
            try:
                # Use cached validations if available
                if validated_terms:
                    return {
                        'text': text,
                        'confidence': 0.6,
                        'validated': True,
                        'medical_terms_found': medical_terms,
                        'validated_terms': validated_terms,
                        'fallback': 'cached_validations'
                    }
            except Exception as fallback_error:
                logger.error(f"Fallback error: {str(fallback_error)}")
            
            return {
                'error': 'validation_failed',
                'message': str(e),
                'original_text': text,
                'fallback': 'complete_failure'
            }

async def translate_text(text, source_lang, target_lang):
    """
    Translate text using Google Translate API with optimizations and error handling
    """
    try:
        # Normalize language codes
        norm_source = normalize_language_code(source_lang)
        norm_target = normalize_language_code(target_lang)
# Cache key generator
def generate_cache_key(text: str, source_lang: str = None, target_lang: str = None) -> str:
    if source_lang and target_lang:
        return f"{source_lang}:{target_lang}:{text}"
    return f"validation:{text}"

# Cache manager
def cache_response(key: str, response: dict):
    response_cache[key] = {
        'data': response,
        'timestamp': datetime.now()
    }

def get_cached_response(key: str) -> Optional[dict]:
    if key in response_cache:
        cache_entry = response_cache[key]
        if datetime.now() - cache_entry['timestamp'] < timedelta(seconds=CACHE_TIMEOUT):
            return cache_entry['data']
        del response_cache[key]
    return None

# Batch processing for medical terms
@lru_cache(maxsize=1000)
def validate_medical_term_cached(term: str) -> dict:
    """Cache individual medical term validations"""
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Validate this medical term and return JSON"},
                {"role": "user", "content": term}
            ],
            temperature=0.3,
            max_tokens=100
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Error validating medical term {term}: {str(e)}")
        return {"error": str(e)}

async def batch_validate_medical_terms(terms: List[str]) -> Dict[str, Any]:
    """Process multiple medical terms in parallel"""
    tasks = []
    with ThreadPoolExecutor() as executor:
        for term in terms:
            if cached_result := get_cached_response(f"term:{term}"):
                tasks.append(asyncio.create_task(asyncio.to_thread(lambda: cached_result)))
            else:
                tasks.append(asyncio.create_task(asyncio.to_thread(validate_medical_term_cached, term)))
    
    results = await asyncio.gather(*tasks)
    return {term: result for term, result in zip(terms, results)}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def retry_api_call(func, *args, **kwargs):
    """Generic retry mechanism for API calls"""
    try:
        return await func(*args, **kwargs)
    except Exception as e:
        logger.error(f"API call failed: {str(e)}")
        raise

# Early return for high-confidence terms
def is_high_confidence_term(term: str, threshold: float = 0.95) -> bool:
    """Check if a term can skip full validation"""
    cache_key = f"confidence:{term}"
    if cached_conf := get_cached_response(cache_key):
        return cached_conf.get('confidence', 0) > threshold
    return False

# Request pooling for translations
class TranslationPool:
    def __init__(self, max_size=10, timeout=1.0):
        self.pool = deque(maxlen=max_size)
        self.timeout = timeout
        self._last_flush = time.time()

    async def add_request(self, text: str, source_lang: str, target_lang: str) -> Dict:
        self.pool.append((text, source_lang, target_lang))
        
        if len(self.pool) >= self.pool.maxlen or time.time() - self._last_flush > self.timeout:
            return await self.flush()
        return None

    async def flush(self) -> Dict:
        if not self.pool:
            return {}

        texts, sources, targets = zip(*self.pool)
        self.pool.clear()
        self._last_flush = time.time()

        try:
            translator = Translator()
            translations = translator.translate(list(texts), src=sources[0], dest=targets[0])
            return {text: trans for text, trans in zip(texts, translations)}
        except Exception as e:
            logger.error(f"Batch translation failed: {str(e)}")
            return {}

# Initialize translation pool
translation_pool = TranslationPool()
        
        if not norm_source:
            raise ValueError(f"Unsupported source language: {source_lang}")
        if not norm_target:
            raise ValueError(f"Unsupported target language: {target_lang}")
        
        # Special handling for Chinese variants
        if target_lang.startswith('zh'):
            target_lang = 'zh-CN'  # Default to Simplified Chinese
        
        # Validate medical terms before translation
        validated = validate_medical_terms(text)
        text_to_translate = validated.get('corrected_text', text) if isinstance(validated, dict) and 'corrected_text' in validated else text
        
        translator = Translator()
        translation = translator.translate(
            text_to_translate,
            src=source_lang,
            dest=target_lang
        )
        
        result = {
            'text': translation.text if hasattr(translation, 'text') else str(translation),
            'source_lang': translation.src if hasattr(translation, 'src') else source_lang,
            'target_lang': translation.dest if hasattr(translation, 'dest') else target_lang,
            'confidence': translation.confidence if hasattr(translation, 'confidence') else None,
            'medical_validation': validated if isinstance(validated, dict) else None
        }
        
        # Validate translated medical terms
        if norm_target != 'en':  # If not translating to English, validate the translated text
            translated_validation = validate_medical_terms(result['text'])
            if isinstance(translated_validation, dict) and 'corrected_text' in translated_validation:
                result['text'] = translated_validation['corrected_text']
                result['translated_validation'] = translated_validation
        
        return result
        
    except ValueError as e:
        print(f"Language code error: {str(e)}")
        return {
            'error': 'invalid_language',
            'message': str(e)
        }
    except Exception as e:
        print(f"Translation error: {str(e)}")
        return {
            'error': 'translation_failed',
            'message': str(e)
        }
