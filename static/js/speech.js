class SpeechHandler {
    constructor() {
        this.recognition = null;
        this.synthesis = window.speechSynthesis;
        this.isRecording = false;
        this.timeoutId = null;
        this.audioContext = null;
        this.audioStream = null;
        this.volumeProcessor = null;
        this.noSpeechTimeout = null;
        this.initializeSpeechRecognition();
    }

    async initializeSpeechRecognition() {
        if (!('webkitSpeechRecognition' in window)) {
            document.dispatchEvent(new CustomEvent('speechError', {
                detail: { message: 'Speech recognition is not supported in this browser.' }
            }));
            return;
        }

        try {
            const hasPermission = await this.requestMicrophonePermission();
            if (!hasPermission) {
                document.dispatchEvent(new CustomEvent('speechError', {
                    detail: { 
                        message: 'Microphone permission denied. Please allow microphone access and try again.',
                        type: 'permission'
                    }
                }));
                return;
            }

            this.recognition = new webkitSpeechRecognition();
            this.recognition.continuous = true;
            this.recognition.interimResults = true;
            this.recognition.maxAlternatives = 1;
            
            this.setupRecognitionHandlers();
            
            return true;
        } catch (error) {
            console.error('Speech recognition initialization error:', error);
            document.dispatchEvent(new CustomEvent('speechError', {
                detail: { 
                    message: 'Failed to initialize speech recognition. Please refresh the page.',
                    type: 'error'
                }
            }));
            return false;
        }
    }

    async speak(text, lang) {
        if (!this.synthesis) {
            throw new Error('Speech synthesis not supported');
        }

        // Force cancel any ongoing speech and resume synthesis
        this.synthesis.cancel();
        await new Promise(resolve => setTimeout(resolve, 100));
        this.synthesis.resume();

        // Wait for voices to load
        let voices = this.synthesis.getVoices();
        if (voices.length === 0) {
            await new Promise(resolve => {
                const voicesChanged = () => {
                    voices = this.synthesis.getVoices();
                    if (voices.length > 0) {
                        window.speechSynthesis.removeEventListener('voiceschanged', voicesChanged);
                        resolve();
                    }
                };
                window.speechSynthesis.addEventListener('voiceschanged', voicesChanged);
                // Trigger voice load
                window.speechSynthesis.getVoices();
            });
        }

        // Prefer native voices over Google voices
        const langCode = lang.startsWith('zh') ? 'zh-CN' : lang;
        console.log('Looking for voice for language:', langCode);
        
        // First try native voices
        let voice = voices.find(v => 
            v.lang.toLowerCase().startsWith(langCode.toLowerCase()) && 
            !v.name.toLowerCase().includes('google')
        );

        // Fall back to Google voices if no native voice found
        if (!voice) {
            voice = voices.find(v => 
                v.lang.toLowerCase().startsWith(langCode.toLowerCase())
            );
        }

        if (!voice) {
            // Try browser's default TTS implementation
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = langCode;
            
            try {
                await new Promise((resolve, reject) => {
                    utterance.onend = resolve;
                    utterance.onerror = reject;
                    this.synthesis.speak(utterance);
                });
                return;
            } catch (error) {
                console.warn('Browser TTS failed, trying audio fallback');
            }
            
            // Final fallback - use an audio element
            const audio = new Audio();
            return new Promise((resolve, reject) => {
                audio.src = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encodeURIComponent(text)}&tl=${langCode}&client=tw-ob`;
                audio.onended = resolve;
                audio.onerror = reject;
                audio.play().catch(reject);
            });
        }

        console.log('Selected voice:', voice.name, voice.lang);
        
        return new Promise((resolve, reject) => {
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.voice = voice;
            utterance.lang = voice.lang;
            utterance.rate = 1.0;
            utterance.pitch = 1.0;
            utterance.volume = 1.0;

            let hasStarted = false;
            const timeout = setTimeout(() => {
                if (!hasStarted) {
                    this.synthesis.cancel();
                    // Try audio fallback
                    const audio = new Audio();
                    audio.src = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encodeURIComponent(text)}&tl=${langCode}&client=tw-ob`;
                    audio.onended = resolve;
                    audio.onerror = reject;
                    audio.play().catch(reject);
                }
            }, 3000);

            utterance.onstart = () => {
                hasStarted = true;
                console.log('Speech started with voice:', voice.name);
            };

            utterance.onend = () => {
                clearTimeout(timeout);
                if (hasStarted) {
                    console.log('Speech completed successfully');
                    resolve();
                }
            };

            utterance.onerror = (event) => {
                clearTimeout(timeout);
                console.error('Speech synthesis error:', event);
                // Try audio fallback
                const audio = new Audio();
                audio.src = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encodeURIComponent(text)}&tl=${langCode}&client=tw-ob`;
                audio.onended = resolve;
                audio.onerror = reject;
                audio.play().catch(reject);
            };

            this.synthesis.speak(utterance);
        });
    }

    setupRecognitionHandlers() {
        if (!this.recognition) return;

        this.recognition.onstart = () => {
            document.dispatchEvent(new CustomEvent('speechStatus', {
                detail: { 
                    status: 'Listening - Please speak clearly into your microphone', 
                    type: 'info' 
                }
            }));
            document.getElementById('volumeMeter').style.display = 'block';
            this.startNoSpeechTimeout();
        };

        this.recognition.onresult = (event) => {
            this.resetNoSpeechTimeout();
            let finalTranscript = '';
            let interimTranscript = '';

            for (let i = event.resultIndex; i < event.results.length; i++) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += transcript;
                    document.dispatchEvent(new CustomEvent('speechStatus', {
                        detail: { 
                            status: 'Speech detected! Processing...', 
                            type: 'success' 
                        }
                    }));
                } else {
                    interimTranscript += transcript;
                }
            }

            if (interimTranscript) {
                document.dispatchEvent(new CustomEvent('interimTranscript', {
                    detail: { text: interimTranscript }
                }));
            }

            if (finalTranscript) {
                document.dispatchEvent(new CustomEvent('transcriptionComplete', {
                    detail: { text: finalTranscript }
                }));
            }
        };

        this.recognition.onerror = (event) => {
            console.error('Speech recognition error:', event.error);
            let message = 'An error occurred with speech recognition.';
            let type = 'error';

            switch (event.error) {
                case 'no-speech':
                    message = 'No speech detected. Please speak louder or move closer to the microphone.';
                    type = 'warning';
                    if (this.isRecording && !this.noSpeechTimeout) {
                        this.noSpeechTimeout = setTimeout(() => {
                            this.noSpeechTimeout = null;
                            if (this.isRecording) {
                                this.restartRecognition();
                            }
                        }, 2000);
                    }
                    break;
                case 'audio-capture':
                    message = 'No microphone was found. Ensure it is plugged in and allowed.';
                    type = 'error';
                    break;
                case 'not-allowed':
                    message = 'Microphone permission was denied. Please allow access and try again.';
                    type = 'permission';
                    break;
            }

            document.dispatchEvent(new CustomEvent('speechError', {
                detail: { message, type }
            }));
            
            if (type === 'error') {
                this.stopRecording();
            }
        };

        this.recognition.onend = () => {
            if (this.isRecording) {
                this.restartRecognition();
            } else {
                document.dispatchEvent(new CustomEvent('speechStatus', {
                    detail: { status: 'Recording stopped', type: 'info' }
                }));
            }
        };
    }

    async restartRecognition() {
        try {
            if (this.recognition) {
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            if (this.isRecording) {
                this.recognition.start();
                document.dispatchEvent(new CustomEvent('speechStatus', {
                    detail: { 
                        status: 'Restarting speech recognition...', 
                        type: 'info' 
                    }
                }));
            }
        } catch (error) {
            console.warn('Failed to restart recognition:', error);
            this.stopRecording();
        }
    }

    async testMicrophone() {
        try {
            if (this.audioStream) {
                this.audioStream.getTracks().forEach(track => track.stop());
            }
            if (this.audioContext) {
                await this.audioContext.close();
            }

            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            this.audioStream = await navigator.mediaDevices.getUserMedia({ 
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });

            const analyser = this.audioContext.createAnalyser();
            const microphone = this.audioContext.createMediaStreamSource(this.audioStream);
            const processor = this.audioContext.createScriptProcessor(2048, 1, 1);
            
            microphone.connect(analyser);
            analyser.connect(processor);
            processor.connect(this.audioContext.destination);

            const volumeCallback = (event) => {
                const input = event.inputBuffer.getChannelData(0);
                let sum = 0.0;
                for (const value of input) {
                    sum += value * value;
                }
                const volume = Math.sqrt(sum / input.length);
                const volumePercentage = Math.min(100, Math.round(volume * 400));
                
                document.dispatchEvent(new CustomEvent('volumeLevel', {
                    detail: { level: volumePercentage }
                }));
            };

            processor.onaudioprocess = volumeCallback;
            this.volumeProcessor = processor;

            const track = this.audioStream.getAudioTracks()[0];
            const capabilities = track.getCapabilities();
            const settings = track.getSettings();

            document.dispatchEvent(new CustomEvent('microphoneStatus', {
                detail: {
                    status: 'Microphone connected and working',
                    type: 'success',
                    info: {
                        name: track.label,
                        muted: track.muted,
                        settings: settings,
                        capabilities: capabilities
                    }
                }
            }));

            return true;
        } catch (error) {
            console.error('Microphone test error:', error);
            let message = 'An error occurred while testing the microphone.';
            let type = 'error';

            if (error.name === 'NotAllowedError') {
                message = 'Microphone access was denied. Please allow access in your browser settings.';
                type = 'permission';
            } else if (error.name === 'NotFoundError') {
                message = 'No microphone found. Please connect a microphone and try again.';
            } else if (error.name === 'NotReadableError') {
                message = 'Microphone is in use by another application or not functioning properly.';
            }

            document.dispatchEvent(new CustomEvent('microphoneStatus', {
                detail: {
                    status: message,
                    type: type,
                    error: error
                }
            }));

            return false;
        }
    }

    async stopMicrophoneTest() {
        if (this.volumeProcessor) {
            this.volumeProcessor.disconnect();
            this.volumeProcessor = null;
        }
        if (this.audioContext) {
            await this.audioContext.close();
            this.audioContext = null;
        }
        if (this.audioStream) {
            this.audioStream.getTracks().forEach(track => track.stop());
            this.audioStream = null;
        }
        document.dispatchEvent(new CustomEvent('volumeLevel', {
            detail: { level: 0 }
        }));
    }

    async requestMicrophonePermission() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            stream.getTracks().forEach(track => track.stop());
            return true;
        } catch (error) {
            console.error('Microphone permission error:', error);
            return false;
        }
    }

    async startRecording() {
        if (!this.recognition) {
            await this.initializeSpeechRecognition();
        }
        
        if (this.recognition) {
            try {
                this.recognition.start();
                this.isRecording = true;
                document.dispatchEvent(new CustomEvent('speechStatus', {
                    detail: { status: 'Listening...', type: 'info' }
                }));
            } catch (error) {
                console.error('Error starting recognition:', error);
            }
        }
    }

    stopRecording() {
        if (this.recognition && this.isRecording) {
            this.isRecording = false;
            this.resetNoSpeechTimeout();
            if (this.noSpeechTimeout) {
                clearTimeout(this.noSpeechTimeout);
                this.noSpeechTimeout = null;
            }

            // Immediately hide volume meter
            document.getElementById('volumeMeter').style.display = 'none';
            
            // Reset volume bar
            const volumeBar = document.querySelector('.volume-bar');
            if (volumeBar) {
                volumeBar.style.width = '0%';
            }

            try {
                this.recognition.stop();
            } catch (error) {
                console.warn('Error stopping recognition:', error);
            }
            
            // Dispatch volume level event to ensure UI is updated
            document.dispatchEvent(new CustomEvent('volumeLevel', {
                detail: { level: 0 }
            }));
        }
    }

    startNoSpeechTimeout() {
        this.resetNoSpeechTimeout();
        this.timeoutId = setTimeout(() => {
            if (this.isRecording) {
                document.dispatchEvent(new CustomEvent('speechError', {
                    detail: { 
                        message: 'No speech detected for a while. Please try speaking again.',
                        type: 'warning'
                    }
                }));
            }
        }, 10000);
    }

    resetNoSpeechTimeout() {
        if (this.timeoutId) {
            clearTimeout(this.timeoutId);
            this.timeoutId = null;
        }
    }
}
