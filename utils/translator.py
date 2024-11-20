import os
from googletrans import Translator
import asyncio
import json
import re
import datetime
import logging
import time
from collections import deque, OrderedDict
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from openai import AsyncOpenAI

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client with error handling - Moved after eventlet monkey patching
client = None
def init_openai():
    global client
    try:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OpenAI API key not found in environment")
        client = AsyncOpenAI(api_key=api_key)
        logger.info("OpenAI client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {str(e)}")
        client = None

class RateLimiter:
    def __init__(self, requests_per_minute=50, burst_limit=10):
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.request_times = deque(maxlen=requests_per_minute)
        self.lock = Lock()
        self.backoff_time = 1
        self.last_success = True

    def can_make_request(self):
        with self.lock:
            now = time.time()
            while self.request_times and now - self.request_times[0] > 60:
                self.request_times.popleft()
            
            if len(self.request_times) < min(self.requests_per_minute, self.burst_limit):
                self.request_times.append(now)
                return True
            return False

    def get_wait_time(self):
        with self.lock:
            if not self.request_times:
                return 0
            oldest_request = self.request_times[0]
            return max(0, 60 - (time.time() - oldest_request))

    def update_backoff(self, success):
        with self.lock:
            if success and not self.last_success:
                self.backoff_time = max(1, self.backoff_time / 2)
            elif not success:
                self.backoff_time = min(60, self.backoff_time * 2)
            self.last_success = success

    def get_metrics(self):
        with self.lock:
            return {
                'requests_in_window': len(self.request_times),
                'backoff_time': self.backoff_time,
                'rate_limit_remaining': self.requests_per_minute - len(self.request_times)
            }

# Define medical patterns
MEDICAL_PATTERNS = {
    'measurements': r'\b\d+(?:\.\d+)?\s*(?:mg|mcg|ml|g|kg|mmHg|°[CF]|cm|mm|IU|mEq|L)\b',
    'vital_signs': r'\b(?:BP|HR|RR|SpO2|Temp|GCS|MAP)[:\s]*(?:\d+(?:/\d+)?)\b',
    'common_abbreviations': r'\b(?:IV|IM|SC|PO|PRN|bid|tid|qid|qd|hs|stat|NPO|N/V|SOB|CP)\b',
    'lab_values': r'\b(?:WBC|RBC|Hgb|Hct|PLT|Na\+|K\+|Cl-|HCO3-|BUN|Cr|GFR|AST|ALT)[:\s]*(?:\d+(?:\.\d+)?)\b',
    'anatomical_terms': r'\b(?:lateral|medial|anterior|posterior|superior|inferior|proximal|distal|bilateral)\b',
    'medical_procedures': r'\b(?:MRI|CT|X-ray|EKG|ECG|EEG|PET|ultrasound|biopsy|endoscopy)\b',
    'common_conditions': r'\b(?:hypertension|diabetes|asthma|COPD|CHF|CAD|MI|CVA|DVT|PE)\b'
}

class TranslationCache:
    def __init__(self, max_size=1000):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.lock = Lock()

    def get_key(self, text, source_lang, target_lang):
        return f"{text}:{source_lang}:{target_lang}"

    def get(self, text, source_lang, target_lang):
        with self.lock:
            key = self.get_key(text, source_lang, target_lang)
            if key in self.cache:
                value = self.cache.pop(key)  # Remove and re-insert for LRU
                self.cache[key] = value
                return value
            return None

    def set(self, text, source_lang, target_lang, value):
        with self.lock:
            key = self.get_key(text, source_lang, target_lang)
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)  # Remove oldest item
            self.cache[key] = value

class RequestBatcher:
    def __init__(self, batch_size=10, batch_timeout=0.1):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.current_batch = []
        self.lock = Lock()
        self.batch_event = asyncio.Event()

    async def add_request(self, request):
        with self.lock:
            self.current_batch.append(request)
            if len(self.current_batch) >= self.batch_size:
                self.batch_event.set()

        if len(self.current_batch) == 1:
            asyncio.create_task(self._timeout_handler())

        while True:
            if request['result'].done():
                return await request['result']
            await asyncio.sleep(0.01)

    async def _timeout_handler(self):
        await asyncio.sleep(self.batch_timeout)
        self.batch_event.set()

    async def process_batch(self, processor_func):
        while True:
            await self.batch_event.wait()
            with self.lock:
                batch = self.current_batch
                self.current_batch = []
                self.batch_event.clear()

            if batch:
                results = await processor_func(batch)
                for req, result in zip(batch, results):
                    req['result'].set_result(result)

# Initialize global instances
translation_cache = TranslationCache()
request_batcher = RequestBatcher()
medical_term_executor = ThreadPoolExecutor(max_workers=4)
rate_limiter = RateLimiter()

# Add medical abbreviation mapping
MEDICAL_ABBREVIATIONS = {
    'BP': 'Blood Pressure',
    'HR': 'Heart Rate',
    'RR': 'Respiratory Rate',
    'temp': 'Temperature',
    'O2': 'Oxygen',
    'IV': 'Intravenous',
    'IM': 'Intramuscular',
    'PO': 'Per Os (by mouth)',
    'bid': 'Twice daily',
    'tid': 'Three times daily',
    'qid': 'Four times daily',
    'prn': 'As needed',
    'stat': 'Immediately',
    'NPO': 'Nothing by mouth'
}

@lru_cache(maxsize=1000)
def expand_medical_abbreviation(abbr):
    """Cache-decorated function to expand medical abbreviations"""
    return MEDICAL_ABBREVIATIONS.get(abbr.upper(), abbr)

async def validate_medical_terms_parallel(text):
    """
    Enhanced parallel medical term validation with confidence scoring
    """
    tasks = []
    
    # Split validation tasks
    pattern_chunks = [
        list(MEDICAL_PATTERNS.items())[i:i+3] 
        for i in range(0, len(MEDICAL_PATTERNS), 3)
    ]

    async def process_patterns(patterns):
        terms = []
        for pattern_type, pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                term = match.group()
                expanded = expand_medical_abbreviation(term)
                confidence = calculate_term_confidence(term, pattern_type)
                terms.append({
                    'term': term,
                    'expanded': expanded if expanded != term else None,
                    'type': pattern_type,
                    'position': match.span(),
                    'confidence': confidence
                })
        return terms

    # Create tasks for parallel processing
    for chunk in pattern_chunks:
        task = asyncio.create_task(process_patterns(chunk))
        tasks.append(task)

    # Wait for all tasks to complete
    results = await asyncio.gather(*tasks)
    
    # Combine and sort results
    all_terms = []
    for result in results:
        all_terms.extend(result)

    # Sort by confidence
    all_terms.sort(key=lambda x: x['confidence'], reverse=True)

    return all_terms

def calculate_term_confidence(term, term_type):
    """
    Calculate confidence score for medical terms
    """
    base_confidence = 0.7
    
    # Adjust confidence based on term type
    type_weights = {
        'measurements': 0.9,
        'vital_signs': 0.95,
        'lab_values': 0.85,
        'medical_procedures': 0.8,
        'drug_classes': 0.85,
        'diagnostic_tests': 0.9
    }
    
    confidence = type_weights.get(term_type, base_confidence)
    
    # Adjust for term characteristics
    if term.isupper():  # Common for established abbreviations
        confidence += 0.1
    if re.match(r'\d', term):  # Contains numbers (likely measurements)
        confidence += 0.05
    if len(term) > 3:  # Longer terms more likely to be valid
        confidence += 0.05

    return min(1.0, confidence)

async def process_translation_batch(batch):
    """
    Process a batch of translation requests
    """
    results = []
    for request in batch:
        text = request['text']
        source_lang = request['source_lang']
        target_lang = request['target_lang']
        
        # Check cache first
        cached_result = translation_cache.get(text, source_lang, target_lang)
        if cached_result:
            results.append(cached_result)
            continue

        # Validate medical terms in parallel
        medical_terms = await validate_medical_terms_parallel(text)
        
        # Preserve medical terms
        preserved_terms = {}
        for term_info in medical_terms:
            if term_info['confidence'] > 0.8:
                placeholder = f"__MEDTERM_{len(preserved_terms)}__"
                preserved_terms[placeholder] = term_info['term']
                text = text.replace(term_info['term'], placeholder)

        # Translate
        try:
            translation = await openai_translate(text, source_lang, target_lang)
            
            # Restore medical terms
            translated_text = translation['text']
            for placeholder, term in preserved_terms.items():
                translated_text = translated_text.replace(placeholder, term)

            result = {
                'text': translated_text,
                'source_lang': translation['source_lang'],
                'target_lang': translation['target_lang'],
                'confidence': translation['confidence'],
                'service': translation['service'],
                'medical_terms': medical_terms
            }
            
            # Cache the result
            translation_cache.set(text, source_lang, target_lang, result)
            results.append(result)
            
        except Exception as e:
            results.append({'error': str(e)})

    return results

# Update the main translation function to use batching
async def translate_text(text, source_lang, target_lang):
    """
    Enhanced translation with batching, caching, and improved error handling
    """
    try:
        logger.debug(f"Starting translation request: {source_lang} -> {target_lang}")
        
        # Check cache first
        cached_result = translation_cache.get(text, source_lang, target_lang)
        if cached_result:
            logger.info("Cache hit for translation")
            return cached_result

        # Create a future for this request
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        
        # Add to batch
        request = {
            'text': text,
            'source_lang': source_lang,
            'target_lang': target_lang,
            'result': future
        }
        
        logger.info("Adding translation request to batch")
        result = await request_batcher.add_request(request)
        
        if 'error' in result:
            logger.error(f"Translation error: {result['error']}")
            if 'openai' in str(result.get('message', '')).lower():
                logger.info("Switching to Google Translate fallback")
                # Initialize Google Translate
                translator = Translator()
                translated = translator.translate(text, src=source_lang, dest=target_lang)
                result = {
                    'text': translated.text,
                    'source_lang': source_lang,
                    'target_lang': target_lang,
                    'confidence': 0.85,
                    'service': 'google',
                    'service_switch': 'Switched to Google Translate due to OpenAI service error'
                }
                logger.info("Google Translate fallback successful")
        
        return result

    except Exception as e:
        logger.error(f"Translation error: {str(e)}", exc_info=True)
        return {
            'error': 'translation_failed',
            'message': str(e),
            'details': {
                'source_lang': source_lang,
                'target_lang': target_lang,
                'timestamp': datetime.datetime.now().isoformat()
            }
        }

async def openai_translate(text, source_lang, target_lang, max_retries=3):
    """
    Translate text using OpenAI's GPT-4 model with medical context and rate limiting
    """
    metrics = rate_limiter.get_metrics()
    logger.info(f"Current API usage metrics: {metrics}")

    retry_count = 0
    while retry_count < max_retries:
        try:
            if not rate_limiter.can_make_request():
                wait_time = rate_limiter.get_wait_time()
                logger.warning(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                await asyncio.sleep(wait_time)
                continue

            # Prepare system prompt with medical context
            system_prompt = """You are an expert medical translator with deep knowledge of:
            1. Medical terminology across languages
            2. Healthcare procedures and protocols
            3. Pharmaceutical terms and medications
            4. Anatomical terminology
            5. Medical abbreviations and their equivalents
            
            Translate the text while:
            - Preserving medical accuracy
            - Maintaining technical precision
            - Using appropriate medical terminology in the target language
            - Keeping medical measurements and values unchanged
            """
            
            # Create the translation prompt
            user_prompt = f"""Translate the following text from {source_lang} to {target_lang}. 
            Preserve all medical terms, measurements, and numerical values.
            
            Text to translate: {text}
            
            Return only the translated text without explanations or notes."""
            
            response = await client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            rate_limiter.update_backoff(True)
            translated_text = response.choices[0].message.content.strip()
            
            return {
                'text': translated_text,
                'source_lang': source_lang,
                'target_lang': target_lang,
                'confidence': 0.95,
                'service': 'openai',
                'metrics': rate_limiter.get_metrics()
            }
            
        except Exception as e:
            retry_count += 1
            rate_limiter.update_backoff(False)
            
            error_type = str(e)
            if 'insufficient_quota' in error_type:
                logger.error("OpenAI API quota exceeded")
                raise ValueError("OpenAI quota exceeded")
            
            if retry_count < max_retries:
                wait_time = rate_limiter.get_wait_time()
                logger.warning(f"Attempt {retry_count} failed. Waiting {wait_time:.2f} seconds before retry")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"All retry attempts failed: {str(e)}")
                raise e

async def translate_text(text, source_lang, target_lang):
    """
    Enhanced translation with OpenAI primary and Google Translate fallback
    """
    try:
        logger.debug(f"Starting translation request: {source_lang} -> {target_lang}")
        
        # Validate OpenAI client
        if not client:
            logger.error("OpenAI client not initialized, falling back to Google Translate")
            raise ValueError("OpenAI client not available")

        # Normalize language codes
        source_lang = source_lang.lower()[:2]
        target_lang = target_lang.lower()[:2]
        
        # Check cache first
        cached_result = translation_cache.get(text, source_lang, target_lang)
        if cached_result:
            logger.debug("Translation found in cache")
            return cached_result

        # Validate and extract medical terms
        medical_terms = await validate_medical_terms_parallel(text)
        preserved_terms = {}
        
        # Create placeholders for medical terms
        for i, term_info in enumerate(medical_terms):
            if term_info['confidence'] > 0.8:
                placeholder = f"__MEDTERM_{i}__"
                preserved_terms[placeholder] = term_info['term']
                text = text.replace(term_info['term'], placeholder)

        try:
            # Try OpenAI translation first
            logger.debug("Attempting OpenAI translation")
            translation = await openai_translate(text, source_lang, target_lang)
            translated_text = translation['text']
            service = 'openai'
            confidence = 0.95
            logger.info("OpenAI translation successful")
            
        except Exception as e:
            logger.warning(f"OpenAI translation failed: {str(e)}, falling back to Google Translate")
            
            # Fall back to Google Translate
            try:
                translator = Translator()
                google_translation = translator.translate(
                    text,
                    src=source_lang,
                    dest=target_lang
                )
                translated_text = google_translation.text
                service = 'google'
                confidence = 0.85
                logger.info("Google Translate fallback successful")
                
            except Exception as google_error:
                logger.error(f"Google Translate fallback failed: {str(google_error)}")
                raise ValueError(f"Both translation services failed. Last error: {str(google_error)}")

        # Restore preserved medical terms
        for placeholder, term in preserved_terms.items():
            translated_text = translated_text.replace(placeholder, term)

        result = {
            'translated': translated_text,
            'source_lang': source_lang,
            'target_lang': target_lang,
            'confidence': confidence,
            'translation_service': service,
            'medical_terms': medical_terms
        }

        # Cache the result
        translation_cache.set(text, source_lang, target_lang, result)
        logger.debug("Translation completed and cached")
        
        return result

    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        return {
            'error': 'translation_failed',
            'message': str(e),
            'details': {
                'source_lang': source_lang,
                'target_lang': target_lang,
                'error_type': type(e).__name__
            }
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
    Enhanced transcription with medical context and error recovery
    """
    try:
        # Normalize language code
        norm_lang = normalize_language_code(language)
        if not norm_lang:
            raise ValueError(f"Unsupported language code: {language}")

        # Enhanced medical context prompt
        medical_prompt = """
        This is a medical conversation. Please pay special attention to:
        1. Medical terminology and diagnoses
        2. Medication names and dosages
        3. Vital signs and measurements
        4. Medical abbreviations
        5. Anatomical terms
        6. Laboratory values and ranges
        7. Medical procedures and treatments
        8. Patient symptoms and conditions
        """
        
        # Create audio file object for the API with enhanced parameters
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_data,
            language=norm_lang,
            prompt=medical_prompt,
            temperature=0.2,  # Lower temperature for more accurate medical terms
            response_format="verbose_json"
        )
        
        if hasattr(response, 'text'):
            return {
                'text': response.text,
                'language': norm_lang,
                'confidence': response.get('confidence', 1.0),
                'detected_language': response.get('detected_language', norm_lang),
                'segments': response.get('segments', [])
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
    Enhanced medical term extraction with confidence scoring
    """
    medical_terms = []
    
    # Extract terms matching medical patterns
    for pattern_type, pattern in MEDICAL_PATTERNS.items():
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            medical_terms.append({
                'term': match.group(),
                'type': pattern_type,
                'position': match.span(),
                'confidence': 0.9  # High confidence for pattern matches
            })
    
    # Check for medication names
    for med_pattern in MEDICATION_CLASSES:
        matches = re.finditer(med_pattern, text, re.IGNORECASE)
        for match in matches:
            medical_terms.append({
                'term': match.group(),
                'type': 'medication',
                'position': match.span(),
                'confidence': 0.85  # Slightly lower confidence for medication matches
            })
    
    # Extract potential medical terms using capitalization and context
    words = text.split()
    for i, word in enumerate(words):
        # Look for capitalized words that might be medical terms
        if word[0].isupper() and len(word) > 3:
            # Check surrounding context for medical indicators
            context_score = 0
            context_window = words[max(0, i-2):min(len(words), i+3)]
            medical_indicators = ['patient', 'doctor', 'hospital', 'clinic', 'diagnosis', 'treatment']
            
            for indicator in medical_indicators:
                if indicator.lower() in [w.lower() for w in context_window]:
                    context_score += 0.1
            
            if context_score > 0:
                medical_terms.append({
                    'term': word,
                    'type': 'potential_medical_term',
                    'position': (text.index(word), text.index(word) + len(word)),
                    'confidence': min(0.7 + context_score, 0.9)  # Base confidence + context
                })
    
    return medical_terms

def validate_medical_terms(text):
    """
    Enhanced medical terminology validation with context awareness
    """
    try:
        # First pass: Extract potential medical terms
        medical_terms = extract_medical_terms(text)
        
        # If no medical terms found, do a quick validation with GPT
        if not medical_terms:
            return {'text': text, 'confidence': 1.0, 'validated': True}
        
        # Prepare the context for GPT with the identified terms
        context = f"""
        Please validate and correct the following medical text, paying special attention to:
        1. Medical terminology accuracy
        2. Drug names and dosages
        3. Vital signs format
        4. Medical abbreviations
        5. Anatomical terms
        6. Lab values and ranges
        7. Procedure names
        8. Disease terminology

        Identified medical terms:
        {json.dumps([{
            'term': term['term'],
            'type': term['type'],
            'confidence': term['confidence']
        } for term in medical_terms], indent=2)}
        
        Original text: {text}
        
        Please respond with a JSON object containing:
        - corrected_text: the text with corrected medical terms
        - corrections: list of specific corrections made
        - warnings: list of potential medical concerns or dangerous combinations
        - suggestions: list of recommended clarifications or additional information needed
        - confidence: overall confidence score for the corrections
        """
        
        response = sync_client.chat.completions.create(  # Use the synchronous client here
            model="gpt-4",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a medical terminology expert with deep knowledge of healthcare terminology, drug interactions, and medical procedures. Validate and correct medical terms while preserving the original meaning. Return your response in a valid JSON format."
                },
                {"role": "user", "content": context}
            ],
            temperature=0.1,
            max_tokens=800
        )
        
        if response.choices[0].message.content:
            try:
                result = json.loads(response.choices[0].message.content)
                # Add metadata about the validation process
                result.update({
                    'original_text': text,
                    'medical_terms_found': medical_terms,
                    'validation_timestamp': datetime.datetime.utcnow().isoformat(),
                    'model_version': 'gpt-4'
                })
                return result
            except json.JSONDecodeError:
                return {
                    'corrected_text': response.choices[0].message.content,
                    'confidence': 1.0,
                    'validated': True
                }
        else:
            return {
                'text': text,
                'confidence': 0.5,
                'validated': False,
                'message': 'Validation produced no results'
            }
            
    except Exception as e:
        print(f"Medical term validation error: {str(e)}")
        return {
            'error': 'validation_failed',
            'message': str(e),
            'original_text': text
        }

# Initialize rate limiter
rate_limiter = RateLimiter()

# Initialize OpenAI client with API key
# client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))  # This line is now redundant
# It was already initialized in the try-except block

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

# Enhanced medical term patterns
MEDICAL_PATTERNS = {
    'measurements': r'\b\d+(?:\.\d+)?\s*(?:mg|mcg|ml|g|kg|mmHg|°[CF]|cm|mm|IU|mEq|L)\b',
    'vital_signs': r'\b(?:BP|HR|RR|SpO2|Temp|GCS|MAP)[:\s]*(?:\d+(?:/\d+)?)\b',
    'common_abbreviations': r'\b(?:IV|IM|SC|PO|PRN|bid|tid|qid|qd|hs|stat|NPO|N/V|SOB|CP)\b',
    'lab_values': r'\b(?:WBC|RBC|Hgb|Hct|PLT|Na\+|K\+|Cl-|HCO3-|BUN|Cr|GFR|AST|ALT)[:\s]*(?:\d+(?:\.\d+)?)\b',
    'anatomical_terms': r'\b(?:lateral|medial|anterior|posterior|superior|inferior|proximal|distal|bilateral)\b',
    'medical_procedures': r'\b(?:MRI|CT|X-ray|EKG|ECG|EEG|PET|ultrasound|biopsy|endoscopy)\b',
    'common_conditions': r'\b(?:hypertension|diabetes|asthma|COPD|CHF|CAD|MI|CVA|DVT|PE)\b'
}

# Add common medication classes
MEDICATION_CLASSES = [
    r'\b\w+(?:cillin|mycin|olol|sartan|pril|statin|oxetine|azepam|codone)\b',
    r'\b(?:aspirin|tylenol|ibuprofen|acetaminophen|morphine|insulin)\b'
]