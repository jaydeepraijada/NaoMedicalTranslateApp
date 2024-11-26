# Healthcare Translation Web App

## Overview
A real-time healthcare translation application that enables multilingual communication between healthcare providers and patients. The system provides voice-to-text translation with specialized medical terminology support across 15 languages.

## Features
- Real-time voice-to-text transcription
- Medical terminology validation and correction
- Support for 15 languages including English, Spanish, French, German, Chinese, Hindi, Japanese, Korean, Russian, Arabic, Portuguese, Italian, Dutch, Polish, and Turkish
- Voice synthesis with automatic fallbacks
- Mobile-responsive interface
- Volume monitoring and audio quality checks

## Tech Stack
- Backend: Flask with SocketIO
- Frontend: JavaScript, HTML5, CSS3
- APIs: 
  - OpenAI Whisper (Speech Recognition)
  - GPT-4 (Medical Validation)
  - Google Translate API
  - Web Speech API
- Deployment: Replit

## Installation
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables:
   - OPENAI_API_KEY
4. Run the application: `python main.py`

## Usage
1. Select source and target languages
2. Test your microphone
3. Start recording your voice
4. View real-time transcription and translation
5. Use the speak button for audio playback

## Security & Privacy
- No permanent storage of medical information
- Secure API key management
- CORS configuration for controlled access
- Comprehensive error handling

## Live Demo
Access the application at: https://7624f5e6-b207-44ef-aab7-a2daacbf6b10-00-30g8a3tyvnezc.pike.replit.dev/

## License
MIT License

## Contributing
1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request
