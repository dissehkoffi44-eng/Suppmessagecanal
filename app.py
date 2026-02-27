import streamlit as st
import asyncio
import datetime
import nest_asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError

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
defaults = {
    "logged_in": False,
    "session_str": None,
    "api_id": None,
    "api_hash": None,
    "phone": None,
    "code_sent": False,
    "phone_code_hash": None,  # ← stocke le hash retourné par send_code_request
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ====================== BOUCLE ASYNCIO DÉDIÉE ======================
# On crée UNE SEULE boucle réutilisable pour toute la session Streamlit.
# Cela évite que Telethon détecte un changement de boucle entre les runs.
if "_event_loop" not in st.session_state:
    loop = asyncio.new_event_loop()
    st.session_state._event_loop = loop
else:
    loop = st.session_state._event_loop

def run_async(coro):
    """Exécute une coroutine sur la boucle dédiée à la session."""
    return loop.run_until_complete(coro)

# ====================== FONCTIONS ASYNC ======================
async def _send_code(api_id, api_hash, phone):
    """Crée un client frais, envoie le code et sauvegarde la session partielle."""
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    result = await client.send_code_request(phone)
    session_str = client.session.save()
    await client.disconnect()
    return session_str, result.phone_code_hash

async def _sign_in(api_id, api_hash, session_str, phone, code, phone_code_hash, password=None):
    """Reprend la session partielle et finalise la connexion."""
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.connect()
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
    except SessionPasswordNeededError:
        if password:
            await client.sign_in(password=password)
        else:
            await client.disconnect()
            raise
    final_session = client.session.save()
    await client.disconnect()
    return final_session

async def _delete_messages(api_id, api_hash, session_str, channel_input, target_date):
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.connect()

    entity = await client.get_entity(channel_input.strip())

    start_date = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=datetime.timezone.utc)
    end_date = start_date + datetime.timedelta(days=1)

    message_ids = []
    progress_text = st.empty()
    progress_bar = st.progress(0)

    count = 0
    async for message in client.iter_messages(entity, reverse=True, offset_date=start_date):
        if message.date >= end_date:
            break
        message_ids.append(message.id)
        count += 1
        if count % 20 == 0:
            progress_text.text(f"📥 Récupérés : {count} messages...")

    progress_text.text(f"✅ {len(message_ids)} messages trouvés le {target_date}.")

    if not message_ids:
        await client.disconnect()
        return 0

    deleted = 0
    for i in range(0, len(message_ids), 100):
        batch = message_ids[i:i + 100]
        try:
            await client.delete_messages(entity, batch)
            deleted += len(batch)
            progress_bar.progress(int(deleted / len(message_ids) * 100))
            progress_text.text(f"🗑️ Supprimés : {deleted}/{len(message_ids)} messages")
        except FloodWaitError as e:
            progress_text.text(f"⏳ Flood wait {e.seconds}s...")
            await asyncio.sleep(e.seconds)
            await client.delete_messages(entity, batch)
            deleted += len(batch)
        except Exception as e:
            st.warning(f"Erreur sur un lot : {e}")

    await client.disconnect()
    return deleted

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
                    session_str, phone_code_hash = run_async(
                        _send_code(api_id_input, api_hash_input, phone_input)
                    )
                    # Tout est stocké en session state — aucun objet client en mémoire
                    st.session_state.api_id = api_id_input
                    st.session_state.api_hash = api_hash_input
                    st.session_state.phone = phone_input
                    st.session_state.session_str = session_str
                    st.session_state.phone_code_hash = phone_code_hash
                    st.session_state.code_sent = True
                    st.success("Code envoyé sur Telegram ! Vérifiez l'application.")
                except Exception as e:
                    st.error(f"Erreur lors de l'envoi du code : {e}")

    if st.session_state.code_sent:
        st.subheader("Entrez le code reçu")
        code_input = st.text_input("Code (5-6 chiffres)", max_chars=10)
        password_input = st.text_input("Mot de passe 2FA (si activé)", type="password")

        if st.button("✅ Se connecter"):
            with st.spinner("Vérification..."):
                try:
                    final_session = run_async(
                        _sign_in(
                            st.session_state.api_id,
                            st.session_state.api_hash,
                            st.session_state.session_str,
                            st.session_state.phone,
                            code_input,
                            st.session_state.phone_code_hash,
                            password_input if password_input else None,
                        )
                    )
                    st.session_state.session_str = final_session
                    st.session_state.logged_in = True
                    st.session_state.code_sent = False
                    st.success("✅ Connexion réussie !")
                    st.rerun()
                except Exception as e:
                    st.error(f"Échec de connexion : {e}")

else:
    # ====================== INTERFACE PRINCIPALE ======================
    st.success("✅ Connecté")
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

    confirm = st.checkbox("**Je confirme que cette action est irréversible et que j'ai les droits admin.**", key="confirm")

    if st.button("🔥 SUPPRIMER TOUS LES MESSAGES DE CETTE DATE", type="primary", use_container_width=True):
        if not channel_input:
            st.error("Veuillez entrer le canal.")
        elif not confirm:
            st.warning("Cochez la case de confirmation.")
        else:
            with st.spinner("Récupération + suppression en cours... (peut prendre plusieurs minutes)"):
                try:
                    deleted_count = run_async(
                        _delete_messages(
                            st.session_state.api_id,
                            st.session_state.api_hash,
                            st.session_state.session_str,
                            channel_input,
                            target_date,
                        )
                    )
                    if deleted_count > 0:
                        st.balloons()
                        st.success(f"🎉 {deleted_count} messages supprimés avec succès le {target_date} !")
                    else:
                        st.info("Aucun message trouvé à cette date.")
                except Exception as e:
                    st.error(f"Erreur : {e}")

    if st.button("🚪 Déconnexion"):
        st.session_state.logged_in = False
        st.session_state.session_str = None
        st.rerun()

st.caption("App Streamlit • Téléthon • Corrigé le 27/02/2026")
