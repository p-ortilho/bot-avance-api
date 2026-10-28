import httpx
import base64
from app.config import settings
from app.database import supabase

async def send_whatsapp_message(phone: str, text: str):
    """Envia mensagem de texto padrão via Evolution API"""
    url = f"{settings.EVOLUTION_API_URL}/message/sendText/{settings.EVOLUTION_INSTANCE}"
    headers = {"apikey": settings.EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"number": phone, "text": text}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code not in [200, 201]:
            print(f"❌ Erro ao enviar texto: {response.status_code} - {response.text}")

async def send_next_question(phone: str, questions: list, current_index: int):
    """Função auxiliar para avançar o fluxo ou finalizar a inspeção de forma limpa"""
    next_index = current_index + 1
    
    if next_index < len(questions):
        supabase.table("user_sessions").update({"state": "ANSWERING", "current_question_index": next_index}).eq("phone_number", phone).execute()
        next_q = questions[next_index]
        
        if next_q["answer_type"] == "boolean":
            await send_whatsapp_message(phone, f"Próxima pergunta:\n{next_q['question_text']}\n\n👉 *1* - Sim\n👉 *2* - Não")
        else:
            await send_whatsapp_message(phone, f"Próxima pergunta:\n{next_q['question_text']}")
    else:
        # Limpa a sessão ao terminar para permitir nova inspeção no futuro
        supabase.table("user_sessions").delete().eq("phone_number", phone).execute()
        await send_whatsapp_message(phone, "Inspeção concluída e salva com sucesso! Obrigado. 🛠️\n\nEnvie qualquer mensagem quando quiser iniciar uma nova inspeção.")

async def handle_incoming_message(phone: str, message_text: str = None, media_data: dict = None):
    # Limpa o número de telefone
    phone = phone.replace("@s.whatsapp.net", "").replace("+", "")

    # =========================================================================
    # TRAVA DE SEGURANÇA (ALLOWLIST)
    # =========================================================================
    auth_check = supabase.table("authorized_users").select("*").eq("phone_number", phone).eq("is_active", True).execute()
    if not auth_check.data:
        print(f"🚫 Bloqueado: Número não autorizado tentou acessar ({phone})")
        await send_whatsapp_message(phone, "🔒 Acesso negado. Este número não está autorizado a realizar inspeções no sistema Avance.")
        return

    # Comando de escape para cancelar a qualquer momento
    if message_text and message_text.strip().lower() in ["cancelar", "sair", "reiniciar"]:
        supabase.table("user_sessions").delete().eq("phone_number", phone).execute()
        await send_whatsapp_message(phone, "🛑 Inspeção cancelada. Envie qualquer mensagem para iniciar uma nova do zero.")
        return

    # Busca a sessão atual
    response = supabase.table("user_sessions").select("*").eq("phone_number", phone).execute()
    session = response.data[0] if response.data else None

    # Inicializa nova sessão
    if not session:
        supabase.table("user_sessions").insert({
            "phone_number": phone,
            "state": "WAITING_EQUIPMENT",
            "current_question_index": 0
        }).execute()
        await send_whatsapp_message(phone, "Olá! Bem-vindo ao sistema de inspeção Avance.\nPor favor, informe o número do veículo/equipamento (ex: VL15):")
        return

    state = session["state"]

    # =========================================================================
    # ESTADO 1: Validar Equipamento
    # =========================================================================
    if state == "WAITING_EQUIPMENT":
        if not message_text:
            await send_whatsapp_message(phone, "Por favor, digite o número do equipamento (ex: VL15):")
            return

        eq_number = message_text.strip().upper()
        eq_res = supabase.table("equipments").select("*").eq("equipment_number", eq_number).execute()
        
        if not eq_res.data:
            await send_whatsapp_message(phone, f"Equipamento '{eq_number}' não encontrado. Verifique e tente novamente:")
            return
        
        category = eq_res.data[0]["category"]
        inspection_res = supabase.table("inspections").insert({"equipment_number": eq_number, "user_phone": phone}).execute()
        inspection_id = inspection_res.data[0]["id"]

        supabase.table("user_sessions").update({
            "state": "ANSWERING",
            "equipment_number": eq_number,
            "category": category,
            "current_question_index": 0,
            "current_inspection_id": inspection_id
        }).eq("phone_number", phone).execute()

        questions_res = supabase.table("questions").select("*").eq("category", category).order("order_index").execute()
        first_q = questions_res.data[0]

        await send_whatsapp_message(phone, f"Equipamento {eq_number} ({category}) identificado com sucesso!")
        
        if first_q["answer_type"] == "boolean":
            await send_whatsapp_message(phone, f"1ª Pergunta:\n{first_q['question_text']}\n\n👉 *1* - Sim\n👉 *2* - Não")
        else:
            await send_whatsapp_message(phone, f"1ª Pergunta:\n{first_q['question_text']}")
        return

    # =========================================================================
    # ESTADO 2: Respondendo Perguntas
    # =========================================================================
    elif state == "ANSWERING":
        if not message_text:
            await send_whatsapp_message(phone, "Por favor, envie uma resposta válida em formato de texto/número.")
            return

        category = session["category"]
        question_index = session["current_question_index"]
        inspection_id = session["current_inspection_id"]

        questions_res = supabase.table("questions").select("*").eq("category", category).order("order_index").execute()
        questions = questions_res.data
        current_q = questions[question_index]
        ans_type = current_q["answer_type"]

        answer_value = message_text.strip()

        # Validação da resposta
        if ans_type == "boolean":
            if answer_value.lower() in ["sim", "s", "yes", "1"]:
                answer_value = "true"
            elif answer_value.lower() in ["não", "nao", "n", "no", "2"]:
                answer_value = "false"
            else:
                await send_whatsapp_message(phone, "Por favor, responda com *1* (Sim) ou *2* (Não):")
                return
        elif ans_type == "number":
            if not answer_value.replace('.', '', 1).isdigit():
                await send_whatsapp_message(phone, "Por favor, informe apenas números válidos (ex: 45500).")
                return

        # Guarda a resposta principal
        supabase.table("inspection_answers").insert({
            "inspection_id": inspection_id, "question_id": current_q["id"], "answer": answer_value
        }).execute()

        # Verifica as regras dinâmicas do banco de dados para esta pergunta
        req_photo = current_q.get("require_photo_when")
        req_desc = current_q.get("require_description_when")
        
        needs_photo = (req_photo == "always") or (req_photo == answer_value)
        needs_desc = (req_desc == "always") or (req_desc == answer_value)

        # Roteamento baseado nas regras
        if needs_photo:
            supabase.table("user_sessions").update({"state": "WAITING_PHOTO"}).eq("phone_number", phone).execute()
            await send_whatsapp_message(phone, "📸 Por favor, envie uma foto evidenciando esta etapa:")
            return
            
        if needs_desc:
            supabase.table("user_sessions").update({"state": "WAITING_DESCRIPTION"}).eq("phone_number", phone).execute()
            await send_whatsapp_message(phone, "📝 Por favor, digite uma breve observação ou descrição:")
            return

        # Se não precisar nem de foto nem de texto extra, vai para a próxima
        await send_next_question(phone, questions, question_index)
        return

    # =========================================================================
    # ESTADO 3: Recebendo Foto
    # =========================================================================
    elif state == "WAITING_PHOTO":
        if not media_data:
            await send_whatsapp_message(phone, "Por favor, envie uma foto válida usando a câmara ou galeria.")
            return

        category = session["category"]
        question_index = session["current_question_index"]
        inspection_id = session["current_inspection_id"]

        questions_res = supabase.table("questions").select("*").eq("category", category).order("order_index").execute()
        questions = questions_res.data
        current_q = questions[question_index]

        try:
            base64_string = media_data["base64"]
            if "," in base64_string:
                base64_string = base64_string.split(",")[1]

            file_bytes = base64.b64decode(base64_string)
            file_name = f"{inspection_id}/{current_q['id']}.jpg"
            
            # Faz o upload usando o parâmetro correto 'path'
            supabase.storage.from_("inspection-photos").upload(
                path=file_name, 
                file=file_bytes, 
                file_options={"content-type": "image/jpeg"}
            )
            
            public_url = supabase.storage.from_("inspection-photos").get_public_url(file_name)
            supabase.table("inspection_answers").update({"photo_url": public_url}).eq("inspection_id", inspection_id).eq("question_id", current_q["id"]).execute()
            
        except Exception as e:
            print(f"❌ Erro ao guardar foto: {e}")
            await send_whatsapp_message(phone, "Ocorreu um erro ao guardar a foto no nosso sistema. Por favor, tente enviar novamente.")
            return

        # Verifica se, além da foto, esta pergunta também exige uma descrição textual
        ans_res = supabase.table("inspection_answers").select("answer").eq("inspection_id", inspection_id).eq("question_id", current_q["id"]).execute()
        answer_value = ans_res.data[0]["answer"] if ans_res.data else "false"
        
        req_desc = current_q.get("require_description_when")
        needs_desc = (req_desc == "always") or (req_desc == answer_value)

        if needs_desc:
            supabase.table("user_sessions").update({"state": "WAITING_DESCRIPTION"}).eq("phone_number", phone).execute()
            await send_whatsapp_message(phone, "Foto guardada com sucesso! ✅\n\n📝 Agora, por favor, digite uma breve observação:")
            return

        await send_whatsapp_message(phone, "Foto guardada com sucesso! ✅")
        await send_next_question(phone, questions, question_index)
        return

    # =========================================================================
    # ESTADO 4: Recebendo Descrição de Texto
    # =========================================================================
    elif state == "WAITING_DESCRIPTION":
        if not message_text:
            await send_whatsapp_message(phone, "Por favor, digite um texto válido com a sua observação.")
            return

        category = session["category"]
        question_index = session["current_question_index"]
        inspection_id = session["current_inspection_id"]

        questions_res = supabase.table("questions").select("*").eq("category", category).order("order_index").execute()
        questions = questions_res.data
        current_q = questions[question_index]

        # Salva o texto descritivo na nova coluna 'observation'
        supabase.table("inspection_answers").update({"observation": message_text.strip()}).eq("inspection_id", inspection_id).eq("question_id", current_q["id"]).execute()
        
        await send_whatsapp_message(phone, "Observação guardada com sucesso! ✅")
        await send_next_question(phone, questions, question_index)
        return