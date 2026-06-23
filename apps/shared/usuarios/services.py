import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BREVO_EMAIL_ENDPOINT = 'https://api.brevo.com/v3/smtp/email'


class BrevoEmailError(Exception):
    pass


def enviar_correo_brevo(
    destinatario_email,
    destinatario_nombre,
    asunto,
    html_content,
    text_content=None,
):
    if not settings.BREVO_API_KEY or not settings.BREVO_SENDER_EMAIL:
        logger.error(
            'No se pudo enviar correo con Brevo: falta BREVO_API_KEY o '
            'BREVO_SENDER_EMAIL.'
        )
        raise BrevoEmailError('Configuracion de Brevo incompleta.')

    payload = {
        'sender': {
            'name': settings.BREVO_SENDER_NAME,
            'email': settings.BREVO_SENDER_EMAIL,
        },
        'to': [
            {
                'email': destinatario_email,
                'name': destinatario_nombre or destinatario_email,
            }
        ],
        'subject': asunto,
        'htmlContent': html_content,
    }

    if text_content:
        payload['textContent'] = text_content

    try:
        response = requests.post(
            BREVO_EMAIL_ENDPOINT,
            headers={
                'api-key': settings.BREVO_API_KEY,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            json=payload,
            timeout=20,
        )
    except requests.RequestException as error:
        logger.exception('Error conectando con Brevo API: %s', error)
        raise BrevoEmailError('No se pudo conectar con Brevo API.') from error

    if response.status_code >= 400:
        logger.error(
            'Brevo API respondio con error. status_code=%s respuesta=%s',
            response.status_code,
            response.text,
        )
        raise BrevoEmailError('Brevo API rechazo el envio.')

    return response
