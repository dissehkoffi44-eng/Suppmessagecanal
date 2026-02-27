import streamlit as st
import asyncio
import datetime
import nest_asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError

# Permet d'utiliser asyncio dans Streamlit
nest_asyncio.apply()

# ====================== CONFIG STREAMLIT ======================
st.set_page_config(
    page_title="Supprimeur Messages Telegram par Date",
    page_icon="🗑️",
    layout="centered"
)

st.title("🗑️ Supprimeur de messages Telegram par date")
st.markdown("**Supprime en 1 clic tous les messages d'une date donnée dans un canal Telegram.**")
st.warning("⚠️ **ACTION IRRÉVERSIBLE !** Vous devez être administrateur du canal avec le droit « Supprimer les messages ». Utilisez à vos risques et périls.")

# ====================== SESSION STATE ======================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "session_str" not in st.session_state:
    st.session_state.session_str = None
if "api_id" not in st.session_state:
    st.session_state.api_id = None
if "api_hash" not in st.session_state:
    st.session_state.api_hash = None
if "phone" not in st.session_state:
    st.session_state.phone = None
if "code_sent" not in st.session_state:
    st.session_state.code_sent = False

# ====================== FONCTIONS ASYNC ======================
async def create_client(session_str: str = None, api_id: int = None, api_hash: str = None):
    client = TelegramClient(StringSession(session_str), api_id, api_hash) if session_str else TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    return client

async def send_code_request(client, phone: str):
    await client.send_code_request(phone)

async def sign_in_client(client, phone: str, code: str, password: str = None):
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        if password:
            await client.sign_in(password=password)
        else:
            raise

async def get_entity(client, channel_input: str):
    return await client.get_entity(channel_input.strip())

async def delete_messages_on_date(client, entity, target_date: datetime.date):
    start_date = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=datetime.timezone.utc)
    end_date = start_date + datetime.timedelta(days=1)

    message_ids = []
    progress_text = st.empty()
    progress_bar = st.progress(0)

    count = 0
    async for message in client.iter_messages(
        entity,
        reverse=True,
        offset_date=start_date
    ):
        if message.date >= end_date:
            break
        message_ids.append(message.id)
        count += 1
        if count % 20 == 0:
            progress_text.text(f"📥 Récupérés : {count} messages...")

    progress_text.text(f"✅ {len(message_ids)} messages trouvés le {target_date}.")

    if not message_ids:
        return 0

    deleted = 0
    for i in range(0, len(message_ids), 100):
        batch = message_ids[i:i + 100]
        try:
            await client.delete_messages(entity, batch)
            deleted += len(batch)
            prog = int((deleted / len(message_ids)) * 100)
            progress_bar.progress(prog)
            progress_text.text(f"🗑️ Supprimés : {deleted}/{len(message_ids)} messages")
        except FloodWaitError as e:
            progress_text.text(f"⏳ Flood wait {e.seconds}s...")
            await asyncio.sleep(e.seconds)
            await client.delete_messages(entity, batch)
            deleted += len(batch)
        except Exception as e:
            st.warning(f"Erreur sur un lot : {e}")

    return deleted

# ====================== RUN ASYNC CORRIGÉ ======================
def run_async(func, *args, **kwargs):
    """Exécute n'importe quelle fonction asynchrone"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    coro = func(*args, **kwargs)
    return loop.run_until_complete(coro)

# ====================== INTERFACE LOGIN ======================
if not st.session_state.logged_in:
    st.header("🔑 Connexion à votre compte Telegram")

    col1, col2 = st.columns(2)
    with col1:
        api_id_input = st.number_input("API ID (my.telegram.org)", min_value=1, step=1, value=12345)
    with col2:
        api_hash_input = st.text_input("API Hash (my.telegram.org)", type="password", value="")

    phone_input = st.text_input("Numéro de téléphone", placeholder="+33612345678")

    if st.button("📱 Envoyer le code de vérification", type="primary"):
        if not (api_id_input and api_hash_input and phone_input):
            st.error("Veuillez remplir tous les champs.")
        else:
            with st.spinner("Connexion à Telegram..."):
                try:
                    client = run_async(create_client, api_id=api_id_input, api_hash=api_hash_input)
                    run_async(send_code_request, client, phone_input)
                    st.session_state.temp_client = client
                    st.session_state.api_id = api_id_input
                    st.session_state.api_hash = api_hash_input
                    st.session_state.phone = phone_input
                    st.session_state.code_sent = True
                    st.success("Code envoyé sur Telegram ! Vérifiez l’application.")
                except Exception as e:
                    st.error(f"Erreur lors de l'envoi du code : {e}")

    if st.session_state.get("code_sent", False):
        st.subheader("Entrez le code reçu")
        code_input = st.text_input("Code (5-6 chiffres)", max_chars=10)
        password_input = st.text_input("Mot de passe 2FA (si activé)", type="password")

        if st.button("✅ Se connecter"):
            with st.spinner("Vérification..."):
                try:
                    client = st.session_state.temp_client
                    run_async(sign_in_client, client, st.session_state.phone, code_input, password_input if password_input else None)

                    session_str = client.session.save()
                    st.session_state.session_str = session_str
                    st.session_state.logged_in = True
                    st.session_state.code_sent = False
                    del st.session_state.temp_client
                    st.success("✅ Connexion réussie !")
                    st.rerun()
                except Exception as e:
                    st.error(f"Échec de connexion : {e}")

else:
    # ====================== INTERFACE PRINCIPALE ======================
    st.success(f"✅ Connecté")

    st.header("🎯 Configuration de la suppression")

    channel_input = st.text_input(
        "Canal (username ou ID)",
        placeholder="@moncanal ou -1001234567890123"
    )

    target_date = st.date_input(
        "Date des messages à supprimer",
        value=datetime.date.today(),
        max_value=datetime.date.today()
    )

    st.markdown("---")

    if st.button("🔥 SUPPRIMER TOUS LES MESSAGES DE CETTE DATE", type="primary", use_container_width=True):
        if not channel_input:
            st.error("Veuillez entrer le canal.")
        elif st.checkbox("**Je confirme que cette action est irréversible et que j’ai les droits admin.**", key="confirm"):
            with st.spinner("Récupération + suppression en cours... (peut prendre plusieurs minutes)"):
                try:
                    client = run_async(
                        create_client,
                        st.session_state.session_str,
                        st.session_state.api_id,
                        st.session_state.api_hash
                    )

                    entity = run_async(get_entity, client, channel_input)
                    deleted_count = run_async(delete_messages_on_date, client, entity, target_date)

                    if deleted_count > 0:
                        st.balloons()
                        st.success(f"🎉 {deleted_count} messages supprimés avec succès le {target_date} !")
                    else:
                        st.info("Aucun message trouvé à cette date.")

                    run_async(client.disconnect)

                except Exception as e:
                    st.error(f"Erreur : {e}")
        else:
            st.warning("Cochez la case de confirmation.")

    if st.button("🚪 Déconnexion"):
        st.session_state.logged_in = False
        st.session_state.session_str = None
        st.rerun()

st.caption("App Streamlit • Téléthon • Corrigé le 27/02/2026")
