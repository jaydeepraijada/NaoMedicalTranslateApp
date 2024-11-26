document.addEventListener('DOMContentLoaded', () => {
    const socket = io();
    const speechHandler = new SpeechHandler();
    
    // DOM Elements
    const startBtn = document.getElementById('startRecording');
    const stopBtn = document.getElementById('stopRecording');
    const testBtn = document.getElementById('testMicrophone');
    const speakBtn = document.getElementById('speakTranslation');
    const originalText = document.getElementById('originalText');
    const translatedText = document.getElementById('translatedText');
    const sourceLang = document.getElementById('sourceLang');
    const targetLang = document.getElementById('targetLang');
    const statusMessage = document.getElementById('statusMessage');
    const microphoneStatus = document.getElementById('microphoneStatus');
    const volumeMeter = document.getElementById('volumeMeter');
    const volumeBar = volumeMeter.querySelector('.volume-bar');
    const medicalInfo = document.getElementById('medicalInfo');

    // Message timeout tracking
    let messageTimeout = null;

    // Socket Events
    socket.on('connect', () => {
        showStatus('Connected to server', 'success');
    });

    socket.on('translation_response', (data) => {
        translatedText.textContent = data.translated;
        showStatus('Translation complete', 'success');
        
        // Display medical validation info if available
        if (data.medical_validation || data.translated_validation) {
            displayMedicalInfo(data.medical_validation || data.translated_validation);
        }
    });

    socket.on('translation_error', (data) => {
        showStatus(data.error, 'danger', true);
    });

    socket.on('medical_validation_info', (data) => {
        displayMedicalInfo(data);
    });

    // Speech Events
    document.addEventListener('speechStatus', (e) => {
        showStatus(e.detail.status, e.detail.type);
    });

    document.addEventListener('speechError', (e) => {
        showStatus(e.detail.message, 'danger', true);
        if (e.detail.type === 'permission') {
            const retryBtn = document.createElement('button');
            retryBtn.className = 'btn btn-primary mt-2';
            retryBtn.textContent = 'Retry Permission';
            retryBtn.onclick = async () => {
                const hasPermission = await speechHandler.requestMicrophonePermission();
                if (hasPermission) {
                    await speechHandler.initializeSpeechRecognition();
                    statusMessage.removeChild(retryBtn);
                    showStatus('Permission granted. You can now start recording.', 'success');
                }
            };
            statusMessage.appendChild(retryBtn);
        }
        resetRecordingUI();
    });

    document.addEventListener('interimTranscript', (e) => {
        originalText.textContent = e.detail.text;
        originalText.classList.add('transcribing');
    });

    document.addEventListener('transcriptionComplete', (e) => {
        originalText.textContent = e.detail.text;
        originalText.classList.remove('transcribing');
        
        socket.emit('translate_message', {
            text: e.detail.text,
            source_lang: sourceLang.value,
            target_lang: targetLang.value
        });
        showStatus('Processing translation...', 'info');
    });

    // Medical Information Display
    function displayMedicalInfo(data) {
        if (!data) return;
        
        medicalInfo.innerHTML = '';
        let content = '<div class="medical-validation p-3">';
        
        // Display corrections if any
        if (data.corrections && Array.isArray(data.corrections) && data.corrections.length > 0) {
            content += '<h6 class="mb-2">Medical Term Corrections:</h6><ul class="list-unstyled">';
            data.corrections.forEach(correction => {
                // Handle both string and object corrections
                const correctionText = typeof correction === 'object' ? 
                    `Changed "${correction.original}" to "${correction.corrected}"` : 
                    correction;
                content += `<li class="text-info"><i class="fas fa-check-circle"></i> ${correctionText}</li>`;
            });
            content += '</ul>';
        }
        
        // Display warnings if any
        if (data.warnings && Array.isArray(data.warnings) && data.warnings.length > 0) {
            content += '<h6 class="mb-2 text-warning">Medical Warnings:</h6><ul class="list-unstyled">';
            data.warnings.forEach(warning => {
                // Handle both string and object warnings
                const warningText = typeof warning === 'object' ? 
                    warning.message || JSON.stringify(warning) : 
                    warning;
                content += `<li class="text-warning"><i class="fas fa-exclamation-triangle"></i> ${warningText}</li>`;
            });
            content += '</ul>';
        }
        
        // Display non-medical terms if any
        if (data.non_medical_terms && Array.isArray(data.non_medical_terms) && data.non_medical_terms.length > 0) {
            content += '<h6 class="mb-2 text-secondary">Non-Medical Terms Detected:</h6><ul class="list-unstyled">';
            data.non_medical_terms.forEach(term => {
                // Handle both string and object terms
                const termText = typeof term === 'object' ? 
                    term.term || JSON.stringify(term) : 
                    term;
                content += `<li class="text-secondary"><i class="fas fa-question-circle"></i> ${termText}</li>`;
            });
            content += '</ul>';
        }
        
        // Display found medical terms if any
        if (data.medical_terms_found && Array.isArray(data.medical_terms_found) && data.medical_terms_found.length > 0) {
            content += '<h6 class="mb-2">Detected Medical Terms:</h6><ul class="list-unstyled">';
            data.medical_terms_found.forEach(term => {
                if (typeof term !== 'object') return;
                
                let icon = 'heartbeat';
                let colorClass = 'text-info';
                let termType = term.type || 'unknown';
                
                // Assign different icons based on term type
                switch(termType) {
                    case 'measurements':
                        icon = 'ruler';
                        break;
                    case 'vital_signs':
                        icon = 'heart-rate';
                        break;
                    case 'common_abbreviations':
                        icon = 'prescription';
                        break;
                    case 'potential_drug_name':
                        icon = 'capsules';
                        break;
                }
                
                const termText = term.term || JSON.stringify(term);
                content += `<li class="${colorClass}"><i class="fas fa-${icon}"></i> ${termText} (${termType})</li>`;
            });
            content += '</ul>';
        }
        
        // Display confidence score if available
        if (typeof data.confidence === 'number') {
            const confidencePercent = Math.round(data.confidence * 100);
            const confidenceClass = confidencePercent > 80 ? 'text-success' : 
                                  confidencePercent > 60 ? 'text-info' : 
                                  'text-warning';
            content += `<div class="mt-2 ${confidenceClass}">
                <i class="fas fa-chart-line"></i> Validation Confidence: ${confidencePercent}%
            </div>`;
        }
        
        content += '</div>';
        medicalInfo.innerHTML = content;
        medicalInfo.style.display = 'block';
        
        // Auto-hide after some time if no warnings and no non-medical terms
        if ((!data.warnings || data.warnings.length === 0) && 
            (!data.non_medical_terms || data.non_medical_terms.length === 0)) {
            setTimeout(() => {
                medicalInfo.style.display = 'none';
            }, 10000);
        }
    }

    // Microphone Test Events
    let microphoneTestActive = false;

    document.addEventListener('volumeLevel', (e) => {
        if (microphoneTestActive || speechHandler.isRecording) {
            volumeMeter.style.display = 'block';
            volumeBar.style.width = `${e.detail.level}%`;
            
            // Update volume label based on level
            const volumeLabel = volumeMeter.querySelector('.volume-label');
            if (e.detail.level < 5) {
                volumeLabel.textContent = 'No sound detected';
            } else if (e.detail.level < 20) {
                volumeLabel.textContent = 'Low volume';
            } else if (e.detail.level < 60) {
                volumeLabel.textContent = 'Good volume';
            } else {
                volumeLabel.textContent = 'High volume';
            }
        } else {
            volumeMeter.style.display = 'none';
        }
    });

    document.addEventListener('microphoneStatus', (e) => {
        showMicrophoneStatus(e.detail);
    });

    // Button Events
    testBtn.addEventListener('click', async () => {
        if (!microphoneTestActive) {
            testBtn.classList.add('active');
            testBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Test';
            microphoneTestActive = true;
            await speechHandler.testMicrophone();
        } else {
            testBtn.classList.remove('active');
            testBtn.innerHTML = '<i class="fas fa-microphone-alt"></i> Test Microphone';
            microphoneTestActive = false;
            await speechHandler.stopMicrophoneTest();
            microphoneStatus.style.display = 'none';
            volumeMeter.style.display = 'none';
        }
    });

    startBtn.addEventListener('click', async () => {
        try {
            await speechHandler.startRecording();
            startBtn.disabled = true;
            stopBtn.disabled = false;
            testBtn.disabled = true;
            startBtn.classList.add('recording');
            originalText.textContent = '';
            translatedText.textContent = '';
            volumeMeter.style.display = 'block';
        } catch (error) {
            showStatus('Failed to start recording. Please try again.', 'danger', true);
        }
    });

    stopBtn.addEventListener('click', () => {
        resetRecordingUI();
        speechHandler.stopRecording();
    });

    speakBtn.addEventListener('click', async () => {
        const text = translatedText.textContent;
        if (!text) {
            showStatus('No text to speak', 'warning');
            return;
        }

        speakBtn.disabled = true;
        try {
            showStatus('Playing audio...', 'info');
            await speechHandler.speak(text, targetLang.value);
            showStatus('Audio playback completed', 'success');
        } catch (error) {
            console.error('Speech synthesis error:', error);
            showStatus(`Failed to play audio: ${error.message}`, 'danger');
        } finally {
            speakBtn.disabled = false;
        }
    });

    function resetRecordingUI() {
        startBtn.disabled = false;
        stopBtn.disabled = true;
        testBtn.disabled = false;
        startBtn.classList.remove('recording');
        originalText.classList.remove('transcribing');
        volumeMeter.style.display = 'none';
    }

    function showStatus(message, type, persistent = false) {
        // Clear any existing timeout
        if (messageTimeout) {
            clearTimeout(messageTimeout);
            messageTimeout = null;
        }

        statusMessage.textContent = message;
        statusMessage.className = `alert alert-${type}`;
        
        // Add shake animation for errors
        if (type === 'danger') {
            statusMessage.classList.add('shake');
            setTimeout(() => statusMessage.classList.remove('shake'), 500);
        }
        
        statusMessage.style.display = 'block';

        // Auto-hide non-persistent and non-error messages
        if (!persistent && type !== 'danger') {
            messageTimeout = setTimeout(() => {
                if (statusMessage.textContent === message) {
                    statusMessage.style.display = 'none';
                }
            }, 3000);
        } else {
            // For errors and persistent messages, show for longer
            messageTimeout = setTimeout(() => {
                if (statusMessage.textContent === message) {
                    statusMessage.style.display = 'none';
                }
            }, 5000);
        }
    }

    function showMicrophoneStatus(detail) {
        microphoneStatus.textContent = detail.status;
        microphoneStatus.className = `alert alert-${detail.type}`;
        microphoneStatus.style.display = 'block';

        if (detail.type === 'success' && detail.info) {
            const infoText = document.createElement('div');
            infoText.className = 'mt-2 small';
            infoText.innerHTML = `
                <strong>Microphone:</strong> ${detail.info.name}<br>
                <strong>Status:</strong> ${detail.info.muted ? 'Muted' : 'Active'}<br>
                <strong>Sample Rate:</strong> ${detail.info.settings.sampleRate}Hz
            `;
            microphoneStatus.appendChild(infoText);
        }

        if (detail.type === 'permission') {
            const retryBtn = document.createElement('button');
            retryBtn.className = 'btn btn-primary mt-2';
            retryBtn.textContent = 'Retry Permission';
            retryBtn.onclick = async () => {
                const hasPermission = await speechHandler.requestMicrophonePermission();
                if (hasPermission) {
                    microphoneStatus.removeChild(retryBtn);
                    testBtn.click();
                }
            };
            microphoneStatus.appendChild(retryBtn);
        }
    }

    // Add shake animation for error messages
    const style = document.createElement('style');
    style.textContent = `
        @keyframes shake {
            0%, 100% { transform: translateX(-50%) translateX(0); }
            25% { transform: translateX(-50%) translateX(-10px); }
            75% { transform: translateX(-50%) translateX(10px); }
        }
        
        .shake {
            animation: shake 0.5s cubic-bezier(0.36, 0.07, 0.19, 0.97) both;
        }

        .transcribing {
            border-color: var(--bs-primary) !important;
            animation: transcribe-pulse 2s infinite;
        }

        @keyframes transcribe-pulse {
            0% { box-shadow: 0 0 0 0 rgba(var(--bs-primary-rgb), 0.4); }
            70% { box-shadow: 0 0 0 10px rgba(var(--bs-primary-rgb), 0); }
            100% { box-shadow: 0 0 0 0 rgba(var(--bs-primary-rgb), 0); }
        }
    `;
    document.head.appendChild(style);
});