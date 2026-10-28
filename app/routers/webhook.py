from fastapi import APIRouter, Request
from app.services.bot_service import handle_incoming_message

router = APIRouter(prefix="/webhook", tags=["Webhook"])

@router.post("")
async def receive_whatsapp_message(request: Request):
    body = await request.json()
    
    try:
        event = body.get("event")
        if event == "messages.upsert":
            data = body.get("data", {})
            
            # Ignora mensagens enviadas pelo próprio bot
            if data.get("key", {}).get("fromMe", False):
                return {"status": "ignored"}

            phone = data.get("key", {}).get("remoteJid", "")
            message_content = data.get("message", {})
            
            # Verifica se é uma imagem
            image_message = message_content.get("imageMessage")
            
            # Verifica se é texto ou resposta de menu
            text_body = (
                message_content.get("conversation") or 
                message_content.get("extendedTextMessage", {}).get("text") or
                message_content.get("listResponseMessage", {}).get("title")
            )
            
            # SE RECEBER IMAGEM
            if image_message:
                # O Webhook Base64 ativado no painel envia a imagem aqui
                base64_data = message_content.get("base64") or data.get("base64")
                
                if base64_data:
                    await handle_incoming_message(phone=phone, media_data={"base64": base64_data})
                else:
                    print("❌ Imagem recebida, mas base64 não encontrado. Verifique o painel da Evolution.")
            
            # SE RECEBER TEXTO
            elif text_body:
                await handle_incoming_message(phone=phone, message_text=text_body)
                
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")

    return {"status": "ok"}