import logging
import json
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import UserProfile
from .serial_controller import send_unlock_command, check_esp32_connection
from .ai_services import (
    extract_facial_embedding,
    calculate_cosine_similarity,
    transcribe_audio_whisper,
    verify_speaker_voice,
    extract_voice_embedding,
)

logger = logging.getLogger(__name__)

FACE_SIMILARITY_THRESHOLD = 0.40  # Cosine similarity threshold for InsightFace


@ensure_csrf_cookie
def home_view(request):
    """
    Vista 1: Hub / Página Principal del Sistema de Cerradura Biométrica.
    Ofrece la navegación entre el módulo de registro de usuarios y el módulo de desbloqueo.
    """
    user_count = UserProfile.objects.filter(is_active=True).count()
    serial_info = check_esp32_connection()
    context = {
        'user_count': user_count,
        'serial_info': serial_info,
    }
    return render(request, 'lock_app/home.html', context)


@ensure_csrf_cookie
def register_view(request):
    """
    Vista 2: Módulo de Registro Biométrico de Usuarios.
    Permite capturar Nombre, Frase Secreta, Rostro (Webcam) y Muestra de Voz (Micrófono).
    """
    serial_info = check_esp32_connection()
    return render(request, 'lock_app/register.html', {'serial_info': serial_info})


@ensure_csrf_cookie
def unlock_view(request):
    """
    Vista 3: Módulo de Operación / Desbloqueo Biométrico 3-FA (Push-To-Talk).
    Permite a un usuario autenticarse mediante Rostro + Frase + Voz para activar la cerradura ESP32.
    """
    users = UserProfile.objects.filter(is_active=True)
    serial_info = check_esp32_connection()
    context = {
        'users': users,
        'user_count': users.count(),
        'serial_info': serial_info,
    }
    return render(request, 'lock_app/unlock.html', context)


def serial_status_api(request):
    """
    API endpoint para consultar en tiempo real si el ESP32 está físicamente conectado.
    """
    status = check_esp32_connection()
    return JsonResponse(status)


@require_http_methods(["POST"])
def register_user(request):
    """
    API endpoint de registro: Procesa el formulario con Nombre, Imagen (Rostro) y Audio (Muestra de voz).
    Utiliza Faster-Whisper para auto-generar y guardar la frase secreta de la voz, y SpeechBrain para la huella vocal.
    """
    try:
        name = request.POST.get('name', '').strip()
        image_file = request.FILES.get('image')
        audio_file = request.FILES.get('audio')

        if not name or not image_file or not audio_file:
            return JsonResponse({
                'success': False,
                'message': 'Por favor ingresa el Nombre, toma la Captura de Rostro y graba una muestra de voz.'
            }, status=400)

        # 1. Extraer Rostro con InsightFace
        image_bytes = image_file.read()
        face_detected, face_embedding, face_msg = extract_facial_embedding(image_bytes)

        if not face_detected or face_embedding is None:
            return JsonResponse({
                'success': False,
                'message': f"No se pudo detectar el rostro para el registro: {face_msg}"
            }, status=400)

        # 2. Procesar Muestra de Voz (Whisper STT & SpeechBrain Biometría Vocal)
        phrase = None
        voice_vector = None
        voice_details = "Sin muestra de voz registrada."

        if audio_file:
            audio_bytes = audio_file.read()
            
            # Transcribir audio con Faster-Whisper para establecer la frase de referencia exacta
            whisper_text = transcribe_audio_whisper(audio_bytes)
            if whisper_text and len(whisper_text.strip()) > 0:
                phrase = whisper_text.strip()
                logger.info(f"[Register] Frase generada automáticamente por Whisper: '{phrase}'")

            # Extraer huella de voz con SpeechBrain
            v_success, voice_vector, voice_details = extract_voice_embedding(audio_bytes)

        if not phrase:
            phrase = "sesamo abrete"  # Frase por defecto si no se proporcionó audio ni texto

        user = UserProfile(name=name, secret_phrase=phrase)
        user.set_facial_embedding(face_embedding)

        if voice_vector is not None:
            user.set_voice_embedding(voice_vector)

        if audio_file:
            user.voice_sample = audio_file

        user.save()
        logger.info(f"[Views] Nuevo usuario registrado: '{user.name}' | Frase Whisper: '{phrase}'")

        return JsonResponse({
            'success': True,
            'message': f"¡Usuario '{user.name}' registrado exitosamente!",
            'user_id': user.id,
            'assigned_phrase': phrase,
            'face_status': '✓ Biometría Facial Registrada (InsightFace 512-d)',
            'voice_status': f"✓ Biometría Vocal Registrada (SpeechBrain). {voice_details}" if audio_file else "⚠️ Sin grabación de voz."
        })

    except Exception as e:
        logger.exception("[Views] Error registrando usuario")
        return JsonResponse({'success': False, 'message': f"Error en servidor: {str(e)}"}, status=500)


@require_http_methods(["POST"])
def authenticate_user(request):
    """
    API endpoint de autenticación 3-FA:
    Recibe Foto + Audio y ejecuta la verificación secuencial contra usuarios registrados.
    """
    pipeline_result = {
        'success': False,
        'step1_reception': {'success': False, 'details': ''},
        'step2_facial': {'success': False, 'matched_user': None, 'score': 0.0, 'details': ''},
        'step3_stt': {'success': False, 'transcribed_text': '', 'expected_phrase': '', 'details': ''},
        'step4_phrase_match': {'success': False, 'details': ''},
        'step5_vocal_verification': {'success': False, 'score': 0.0, 'details': ''},
        'step6_esp32_unlock': {'success': False, 'serial_info': None, 'details': ''},
        'message': ''
    }

    try:
        # Check if database has users
        active_users = UserProfile.objects.filter(is_active=True)
        if not active_users.exists():
            pipeline_result['message'] = "Acceso Denegado: No hay usuarios registrados en el sistema. Registre un usuario primero."
            return JsonResponse(pipeline_result, status=200)

        # Paso 1: Recibir Multimedia
        image_file = request.FILES.get('image')
        audio_file = request.FILES.get('audio')

        if not image_file or not audio_file:
            pipeline_result['step1_reception']['details'] = "Falta la captura de imagen o la grabación de audio."
            pipeline_result['message'] = "Paso 1 fallido: Archivos multimedia no recibidos."
            return JsonResponse(pipeline_result, status=400)

        image_bytes = image_file.read()
        audio_bytes = audio_file.read()

        pipeline_result['step1_reception'] = {
            'success': True,
            'details': f"Imagen ({len(image_bytes)} B) y Audio ({len(audio_bytes)} B) recibidos."
        }

        # Paso 2: Extraer Rostro (InsightFace) y buscar coincidencias en la BD real
        face_detected, current_embedding, face_msg = extract_facial_embedding(image_bytes)

        if not face_detected or current_embedding is None:
            pipeline_result['step2_facial']['details'] = f"Reconocimiento Facial Fallido: {face_msg}"
            pipeline_result['message'] = "Acceso Denegado - Paso 2: No se detectó un rostro válido."
            return JsonResponse(pipeline_result, status=200)

        matched_user = None
        best_similarity = -1.0

        for user in active_users:
            user_vec = user.get_facial_embedding()
            if user_vec is not None and len(user_vec) > 0:
                sim = calculate_cosine_similarity(current_embedding, user_vec)
                if sim > best_similarity:
                    best_similarity = sim
                    if sim >= FACE_SIMILARITY_THRESHOLD:
                        matched_user = user

        if matched_user is None:
            pipeline_result['step2_facial'] = {
                'success': False,
                'score': float(best_similarity),
                'details': f"Rostro no coincide con ningún usuario registrado (Similitud max: {best_similarity:.2f})."
            }
            pipeline_result['message'] = "Acceso Denegado - Paso 2: Rostro no registrado."
            return JsonResponse(pipeline_result, status=200)

        pipeline_result['step2_facial'] = {
            'success': True,
            'matched_user': matched_user.name,
            'score': round(float(best_similarity), 3),
            'details': f"Usuario identificado: '{matched_user.name}' (Similitud: {best_similarity:.2f})."
        }

        # Paso 3: Transcribir Audio con Faster-Whisper
        transcribed_text = transcribe_audio_whisper(audio_bytes)
        expected_phrase = matched_user.secret_phrase.strip().lower()
        clean_transcription = transcribed_text.strip().lower()

        pipeline_result['step3_stt'] = {
            'success': True if clean_transcription else False,
            'transcribed_text': transcribed_text,
            'expected_phrase': matched_user.secret_phrase,
            'details': f"Texto STT: '{transcribed_text}'"
        }

        # Paso 4: Coincidencia de Frase Clave
        import re
        norm_transcription = re.sub(r'[^\w\s]', '', clean_transcription)
        norm_expected = re.sub(r'[^\w\s]', '', expected_phrase)

        phrase_matches = (norm_expected in norm_transcription) or (norm_transcription in norm_expected)

        if not phrase_matches:
            pipeline_result['step4_phrase_match'] = {
                'success': False,
                'details': f"La frase esperada ('{matched_user.secret_phrase}') no coincide con lo dicho ('{transcribed_text}')."
            }
            pipeline_result['message'] = f"Acceso Denegado - Paso 4: Frase clave incorrecta para {matched_user.name}."
            return JsonResponse(pipeline_result, status=200)

        pipeline_result['step4_phrase_match'] = {
            'success': True,
            'details': f"Frase secreta verificada correctamente ('{matched_user.secret_phrase}')."
        }

        # Paso 5: Biometría Vocal (SpeechBrain)
        voice_ref_path = matched_user.voice_sample.path if matched_user.voice_sample else None
        voice_vec = matched_user.get_voice_embedding()

        voice_verified, voice_score, voice_msg = verify_speaker_voice(
            audio_bytes=audio_bytes,
            user_voice_embedding=voice_vec,
            reference_audio_path=voice_ref_path
        )

        pipeline_result['step5_vocal_verification'] = {
            'success': voice_verified,
            'score': round(float(voice_score), 3),
            'details': voice_msg
        }

        if not voice_verified:
            pipeline_result['message'] = f"Acceso Denegado - Paso 5: Biometría vocal no coincide para {matched_user.name}."
            return JsonResponse(pipeline_result, status=200)

        # Paso 6: Apertura Física ESP32
        serial_result = send_unlock_command(command=b'OPEN\n')
        
        pipeline_result['step6_esp32_unlock'] = {
            'success': serial_result['success'],
            'serial_info': serial_result,
            'details': serial_result['message']
        }

        pipeline_result['success'] = True
        pipeline_result['message'] = f"¡AUTENTICACIÓN EXITOSA! Bienvenido {matched_user.name}. Cerradura Desbloqueada."
        return JsonResponse(pipeline_result, status=200)

    except Exception as e:
        logger.exception("[Pipeline] Excepción en autenticación")
        pipeline_result['message'] = f"Error interno del servidor: {str(e)}"
        return JsonResponse(pipeline_result, status=500)
