import base64
import logging
from email.message import EmailMessage
from googleapiclient.errors import HttpError
from Managers.autenticador import GoogleOAUTH

# Seguindo a sua lógica de hierarquia de logs
log = logging.getLogger("Robo E-Processo.Gmail")

class GmailManager:
    """Lida com chamadas de API do Gmail utilizando uma instância do google_oauth"""
    
    def __init__(self, google_oauth: GoogleOAUTH):
        # Aqui pegamos o serviço já construído (build('gmail', 'v1', ...))
        self.service = google_oauth.get_oauth2_gmail()
        self.user_email = google_oauth.get_user_email()
        log.debug(f"GmailManager instanciado para o usuário: {self.user_email}")

    def enviar_email(self, destinatario, assunto, corpo, is_html=False):
        """
        Envia um e-mail via Gmail API.
        """
        try:
            log.info(f"Preparando envio de e-mail para: {destinatario}")
            
            mensagem = EmailMessage()
            mensagem["To"] = destinatario
            mensagem["From"] = self.user_email
            mensagem["Subject"] = assunto
            
            if is_html:
                mensagem.set_content("Seu leitor de e-mail não suporta HTML.")
                mensagem.add_alternative(corpo, subtype="html")
            else:
                mensagem.set_content(corpo)

            raw_message = base64.urlsafe_b64encode(mensagem.as_bytes()).decode("utf-8")
            corpo_requisicao = {"raw": raw_message}
            
            enviado = self.service.users().messages().send(userId="me", body=corpo_requisicao).execute()
            
            log.info(f"✅ E-mail enviado com sucesso! ID: {enviado['id']}")
            return enviado

        except HttpError as error:
            log.error(f"[ERRO GMAIL API] Falha no envio: {error}")
            return None
        except Exception as e:
            log.error(f"[ERRO INESPERADO GMAIL] {str(e)}")
            return None