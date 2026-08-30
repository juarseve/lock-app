/**
 * Push-To-Talk & Biometric Media Capture Controller (Vanilla JS)
 * Captures live webcam frame via <canvas> and records audio via MediaRecorder.
 * Sends multipart/form-data POST request to Django backend.
 */

document.addEventListener('DOMContentLoaded', () => {
    // DOM Element References
    const webcamVideo = document.getElementById('webcam-feed');
    const snapshotCanvas = document.getElementById('snapshot-canvas');
    const pttButton = document.getElementById('ptt-button');
    const pttTimer = document.getElementById('ptt-timer');
    const pttInstruction = document.getElementById('ptt-instruction');
    const reticleOverlay = document.querySelector('.reticle-overlay');
    const lockBanner = document.getElementById('lock-state-banner');

    // Pipeline Step Elements
    const stepCards = {
        1: document.getElementById('step-1-card'),
        2: document.getElementById('step-2-card'),
        3: document.getElementById('step-3-card'),
        4: document.getElementById('step-4-card'),
        5: document.getElementById('step-5-card'),
    };

    // State variables
    let mediaStream = null;
    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;
    let capturedImageBlob = null;
    let recordStartTime = 0;
    let timerInterval = null;

    // 1. Initialize Webcam & Microphone Stream
    async function initMediaDevices() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            let errorMsg = 'Tu navegador no permite acceso a la cámara/micrófono en este contexto.';
            if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
                errorMsg += '\n\n⚠️ MOTIVO: Los navegadores bloquean la cámara/micrófono en conexiones HTTP no seguras.' +
                    '\n\nPara solucionar esto:' +
                    '\n1. Accede desde Debian usando http://localhost:8000' +
                    '\n2. O habilita en Chrome del cliente: chrome://flags/#unsafely-treat-insecure-origin-as-secure e incluye http://' + window.location.host;
            }
            console.error('[PTTController]', errorMsg);
            alert(errorMsg);
            return;
        }

        try {
            // Try ideal HD resolution first
            mediaStream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
                audio: true
            });
            webcamVideo.srcObject = mediaStream;
            console.log('[PTTController] Video and Audio streams initialized successfully.');
        } catch (primaryErr) {
            console.warn('[PTTController] High-res constraints failed, falling back to default constraints:', primaryErr);
            try {
                // Fallback to basic video & audio constraints
                mediaStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
                webcamVideo.srcObject = mediaStream;
                console.log('[PTTController] Basic video & audio stream initialized.');
            } catch (err) {
                console.error('[PTTController] Error accessing webcam/microphone:', err);
                let msg = 'No se pudo acceder a la cámara o al micrófono.\n';
                if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                    msg += 'Debes otorgar permisos de Cámara y Micrófono en el navegador.';
                } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
                    msg += 'No se detectó ninguna cámara o micrófono físico conectado.';
                } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
                    msg += 'La cámara o micrófono está siendo usado por otra aplicación (ej: Zoom, Meet, u otra pestaña).';
                } else {
                    msg += `Detalle: ${err.message || err.name}`;
                }
                alert(msg);
            }
        }
    }

    initMediaDevices();

    // 2. Helper function to capture current webcam frame to Canvas
    function captureWebcamFrame() {
        if (!webcamVideo.videoWidth) return null;
        snapshotCanvas.width = webcamVideo.videoWidth;
        snapshotCanvas.height = webcamVideo.videoHeight;
        const ctx = snapshotCanvas.getContext('2d');
        ctx.drawImage(webcamVideo, 0, 0, snapshotCanvas.width, snapshotCanvas.height);
        
        return new Promise((resolve) => {
            snapshotCanvas.toBlob((blob) => {
                resolve(blob);
            }, 'image/jpeg', 0.92);
        });
    }

    // 3. Start Recording (On Push Down)
    async function startRecording(e) {
        if (e) e.preventDefault();
        if (isRecording || !mediaStream) return;

        isRecording = true;
        audioChunks = [];

        // Visual feedback
        pttButton.classList.add('recording');
        reticleOverlay.classList.add('active');
        pttInstruction.textContent = "Suelte para Autenticar";
        pttTimer.style.display = "block";
        
        recordStartTime = Date.now();
        timerInterval = setInterval(() => {
            const elapsed = ((Date.now() - recordStartTime) / 1000).toFixed(1);
            pttTimer.textContent = `${elapsed}s`;
        }, 100);

        // Capture webcam snapshot frame immediately
        capturedImageBlob = await captureWebcamFrame();
        console.log('[PTTController] Captured frame snapshot.');

        // Initialize MediaRecorder for audio (Extracting only audio tracks to prevent NotSupportedError with audio/webm mimeType)
        try {
            const audioStream = new MediaStream(mediaStream.getAudioTracks());
            const options = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                ? { mimeType: 'audio/webm;codecs=opus' }
                : {};
            
            mediaRecorder = new MediaRecorder(audioStream, options);
            
            mediaRecorder.ondataavailable = (evt) => {
                if (evt.data && evt.data.size > 0) {
                    audioChunks.push(evt.data);
                }
            };

            mediaRecorder.onstop = () => {
                const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
                sendAuthenticationPayload(capturedImageBlob, audioBlob);
            };

            mediaRecorder.start();
            console.log('[PTTController] Audio recording started.');
        } catch (err) {
            console.error('[PTTController] Error starting MediaRecorder:', err);
            stopRecording();
        }
    }

    // 4. Stop Recording (On Release)
    function stopRecording(e) {
        if (e) e.preventDefault();
        if (!isRecording) return;

        isRecording = false;
        clearInterval(timerInterval);

        // Reset Visual Feedback
        pttButton.classList.remove('recording');
        reticleOverlay.classList.remove('active');
        pttInstruction.textContent = "Procesando Biometría 3-FA...";
        pttTimer.style.display = "none";

        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
        }
    }

    // Event Listeners for Push-to-Talk (Mouse & Touch)
    pttButton.addEventListener('mousedown', startRecording);
    pttButton.addEventListener('mouseup', stopRecording);
    pttButton.addEventListener('mouseleave', stopRecording);

    pttButton.addEventListener('touchstart', startRecording, { passive: false });
    pttButton.addEventListener('touchend', stopRecording, { passive: false });

    // Helper to get CSRF token from Django cookie or input
    function getCsrfToken() {
        const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (csrfInput) return csrfInput.value;
        const name = 'csrftoken';
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    // Reset pipeline UI cards
    function resetPipelineUI() {
        Object.values(stepCards).forEach(card => {
            if (card) {
                card.className = 'step-card';
                const badge = card.querySelector('.step-badge');
                if (badge) badge.textContent = 'Pendiente';
                const desc = card.querySelector('.step-desc');
                if (desc) desc.textContent = 'En espera de datos...';
            }
        });
        lockBanner.className = 'lock-state-banner';
        document.getElementById('lock-state-title').textContent = "CERRADURA BLOQUEADA";
        document.getElementById('lock-state-desc').textContent = "Mantenga presionado el botón PTT para iniciar el escaneo biométrico.";
    }

    // Helper to update a step card
    function updateStepCard(stepNumber, passed, badgeText, descText) {
        const card = stepCards[stepNumber];
        if (!card) return;

        card.className = `step-card ${passed ? 'passed' : 'failed'}`;
        const badge = card.querySelector('.step-badge');
        if (badge) badge.textContent = badgeText;
        const desc = card.querySelector('.step-desc');
        if (desc) desc.textContent = descText;
    }

    // 5. Send POST Request with Image + Audio to Django Backend
    async function sendAuthenticationPayload(imageBlob, audioBlob) {
        resetPipelineUI();

        if (!imageBlob || !audioBlob) {
            alert('No se pudo capturar la foto o el audio correctamente.');
            pttInstruction.textContent = "Mantenga presionado para hablar";
            return;
        }

        // Set Step 1 active
        if (stepCards[1]) {
            stepCards[1].className = 'step-card active';
            stepCards[1].querySelector('.step-badge').textContent = 'Enviando...';
        }

        const formData = new FormData();
        formData.append('image', imageBlob, 'webcam_frame.jpg');
        formData.append('audio', audioBlob, 'mic_recording.webm');

        const csrfToken = getCsrfToken();

        try {
            const response = await fetch('/api/authenticate/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                },
                body: formData
            });

            const data = await response.json();
            console.log('[PTTController] Authentication Response:', data);

            // Update UI based on pipeline response
            // Step 1: Reception
            if (data.step1_reception) {
                updateStepCard(1, data.step1_reception.success, 
                    data.step1_reception.success ? 'OK' : 'Error', 
                    data.step1_reception.details);
            }

            // Step 2: Facial Recognition (InsightFace)
            if (data.step2_facial) {
                updateStepCard(2, data.step2_facial.success,
                    data.step2_facial.success ? 'Identificado' : 'No coincidencia',
                    data.step2_facial.details);
            }

            // Step 3: STT (Faster-Whisper) & Step 4: Phrase Match
            if (data.step3_stt && data.step4_phrase_match) {
                const sttPassed = data.step3_stt.success && data.step4_phrase_match.success;
                updateStepCard(3, sttPassed,
                    sttPassed ? 'Verificado' : 'Incorrecto',
                    `${data.step3_stt.details} | ${data.step4_phrase_match.details}`);
            }

            // Step 4: Speaker Verification (SpeechBrain)
            if (data.step5_vocal_verification) {
                updateStepCard(4, data.step5_vocal_verification.success,
                    data.step5_vocal_verification.success ? 'Aprobado' : 'Rechazado',
                    data.step5_vocal_verification.details);
            }

            // Step 5: ESP32 Hardware Relay Command
            if (data.step6_esp32_unlock) {
                updateStepCard(5, data.step6_esp32_unlock.success,
                    data.step6_esp32_unlock.success ? 'Comando Enviado' : 'Error Port',
                    data.step6_esp32_unlock.details);
            }

            // Update Master Lock Banner Status
            if (data.success) {
                lockBanner.className = 'lock-state-banner unlocked';
                document.getElementById('lock-state-title').textContent = "🔓 ACCESO CONCEDIDO - ABIERTO";
                document.getElementById('lock-state-desc').textContent = data.message;
            } else {
                lockBanner.className = 'lock-state-banner denied';
                document.getElementById('lock-state-title').textContent = "🔒 ACCESO DENEGADO";
                document.getElementById('lock-state-desc').textContent = data.message || "Fallo en la autenticación biométrica.";
            }

        } catch (err) {
            console.error('[PTTController] Fetch Error:', err);
            updateStepCard(1, false, 'Error de Red', 'No se pudo contactar al servidor Django.');
            lockBanner.className = 'lock-state-banner denied';
            document.getElementById('lock-state-title').textContent = "ERROR DE SISTEMA";
            document.getElementById('lock-state-desc').textContent = err.message;
        } finally {
            pttInstruction.textContent = "Mantenga presionado para hablar";
        }
    }
});
