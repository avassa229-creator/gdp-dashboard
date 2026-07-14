import datetime
import os
import requests
import streamlit as st
from bs4 import BeautifulSoup

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# --- CONFIGURATION SÉCURISÉE ---
MAX_MESSAGES_PER_SESSION = 15  # Limite pour les utilisateurs normaux
ADMIN_PASSWORD = "21082022"  # 👈 Votre nouveau mot de passe administrateur


def get_api_key():
    """Récupère votre clé API configurée en secret sur le serveur."""
    if "gemini_api_key" in st.session_state and st.session_state.gemini_api_key:
        return st.session_state.gemini_api_key
    env_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None


def web_search_context(query: str) -> str:
    """Cherche sur le web pour actualiser les connaissances si nécessaire."""
    try:
        url = "https://duckduckgo.com"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, params={"q": query}, timeout=6, headers=headers)
        if response.status_code != 200:
            return ""
        soup = BeautifulSoup(response.text, "html.parser")
        snippets = []
        for link in soup.select("a.result__a")[:3]:
            title = link.get_text(strip=True)
            href = link.get("href")
            snippets.append(f"- {title} (Source: {href})")
        return "\n".join(snippets)
    except Exception:
        return ""


def stream_assistant_reply(user_input: str, prenom: str = None, history: list = None):
    """Génère la réponse de Floreina avec votre clé secrète."""
    text = user_input.strip()
    api_key = get_api_key()
    
    if not api_key:
        yield "⚠️ Configuration incomplète : L'administrateur n'a pas configuré la clé API sur le serveur."
        return

    history = history or []

    # Personalisation de l'accueil pour le créateur (Admin)
    est_admin = st.session_state.get("is_admin", False)
    nom_role = "mon Créateur et Développeur" if est_admin else (prenom if prenom else 'un ami')

    system_instruction = (
        "Tu es Floreina, une IA conversationnelle polyvalente, amicale et experte.\n"
        "1. PARLE AVEC LES GENS : Sois chaleureuse, pose des questions, sois naturelle.\n"
        "2. PROPOSER DES SOLUTIONS : Donne des plans d'action clairs, des étapes logiques.\n"
        "3. TROUVER DES RÉPONSES : Réponds précisément à tout (code, calculs, rédaction, culture).\n\n"
        f"Tu discutes actuellement avec {nom_role}. "
        f"Nous sommes le {datetime.datetime.now().strftime('%d/%m/%Y à %H:%M')}."
    )

    web_context = ""
    mots_cles = ["météo", "actu", "aujourd'hui", "nouvelles", "score"]
    if any(kw in text.lower() for kw in mots_cles):
        web_context = web_search_context(text)

    # Exécution Gemini
    if genai and ("gemini" in api_key.lower() or "google" in api_key.lower() or len(api_key) > 30):
        try:
            client = genai.Client(api_key=api_key)
            contents = []
            for msg in history:
                role = "user" if msg["role"] == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
            
            prompt_final = text
            if web_context:
                prompt_final = f"[Données Web] :\n{web_context}\n\nRequête : {text}"
                
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt_final)]))

            response_stream = client.models.generate_content_stream(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.7),
            )
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"Erreur technique : {str(e)}"

    # Exécution OpenAI
    elif OpenAI:
        try:
            client = OpenAI(api_key=api_key)
            messages = [{"role": "system", "content": system_instruction}]
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
            
            prompt_final = text
            if web_context:
                prompt_final = f"[Données Web] :\n{web_context}\n\nRequête : {text}"
            messages.append({"role": "user", "content": prompt_final})

            response_stream = client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, temperature=0.7, stream=True
            )
            for chunk in response_stream:
                if chunk.choices.delta.content:
                    yield chunk.choices.delta.content
        except Exception as e:
            yield f"Erreur technique : {str(e)}"


# --- INTERFACE GRAPHIQUE STREAMLIT ---
st.title("Floreina IA 🤖✨")

# Initialisation des variables de session
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_usage_count" not in st.session_state:
    st.session_state.user_usage_count = 0
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# Barre latérale (Gestion des droits d'accès)
with st.sidebar:
    st.subheader("🔑 Espace Connexion")
    
    # Saisie du mot de passe
    input_password = st.text_input("Code secret Administrateur", type="password", placeholder="Entrez le code...")
    
    if input_password == ADMIN_PASSWORD:
        st.session_state.is_admin = True
        st.success("👑 Mode Administrateur activé ! Accès illimité.")
    else:
        st.session_state.is_admin = False

    st.divider()
    st.subheader("📊 Votre Utilisation")
    
    if st.session_state.is_admin:
        st.info("♾️ Messages : Illimités")
    else:
        restant = MAX_MESSAGES_PER_SESSION - st.session_state.user_usage_count
        st.metric(label="Messages restants", value=max(0, restant))
        if restant <= 0:
            st.error("❌ Quota session atteint.")

# Rendu de l'historique
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Zone d'écriture des messages
if user_query := st.chat_input("Discutez avec Floreina..."):
    
    if not st.session_state.is_admin and st.session_state.user_usage_count >= MAX_MESSAGES_PER_SESSION:
        st.error(f"Quota de {MAX_MESSAGES_PER_SESSION} messages atteint pour les invités.")
    else:
        with st.chat_message("user"):
            st.markdown(user_query)
        st.session_state.messages.append({"role": "user", "content": user_query})
        
        if not st.session_state.is_admin:
            st.session_state.user_usage_count += 1

        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            full_response = ""
            
            for chunk in stream_assistant_reply(
                user_input=user_query,
                prenom=st.session_state.get("user_name", None),
                history=st.session_state.messages[:-1]
            ):
                full_response += chunk
                response_placeholder.markdown(full_response + "▌")
            
            response_placeholder.markdown(full_response)
        
        st.session_state.messages.append({"role": "assistant", "content": full_response})
        st.rerun()
