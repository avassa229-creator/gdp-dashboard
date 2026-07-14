import datetime
import os
import requests
import streamlit as st
from bs4 import BeautifulSoup

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# --- CONFIGURATION SÉCURISÉE ---
MAX_MESSAGES_PER_SESSION = 15  # Limite pour les utilisateurs normaux
ADMIN_PASSWORD = "21082022"  # Votre mot de passe administrateur


def get_api_key():
    """Récupère votre clé Groq configurée en secret sur le serveur."""
    if "groq_api_key" in st.session_state and st.session_state.groq_api_key:
        return st.session_state.groq_api_key
  def get_api_key():
    """Détecteur universel pour trouver la clé API peu importe son nom."""
    # 1. Vérification dans la session active
    for key in ["groq_api_key", "gemini_api_key", "api_key"]:
        if key in st.session_state and st.session_state[key]:
            return st.session_state[key]
    
    # 2. Vérification dans les variables d'environnement système
    for env_var in ["GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"]:
        if os.getenv(env_var):
            return os.getenv(env_var)
            
    # 3. Vérification approfondie dans les secrets du serveur Streamlit
    try:
        # On cherche si un secret existe, peu importe sa casse (majuscule/minuscule)
        for secret_key in st.secrets.keys():
            if secret_key.upper() in ["GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"]:
                return st.secrets[secret_key]
    except Exception:
        pass
        
    return None

    # 1. Vérifie si elle est dans la session Streamlit
    if "groq_api_key" in st.session_state and st.session_state.groq_api_key:
        return st.session_state.groq_api_key
    
    # 2. Vérifie dans l'environnement ou les Secrets système de Streamlit Cloud
    env_key = os.getenv("GROQ_API_KEY")
    if env_key:
        return env_key
        
    try:
        # Recherche prioritaire de la clé Groq ou d'un fallback
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"]
        elif "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
        
    return None
    if env_key:
        return env_key
    try:
        return st.secrets["GROQ_API_KEY"]
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
    """Génère la réponse de Floreina avec votre clé Groq en utilisant l'adresse compatible OpenAI."""
    text = user_input.strip()
    api_key = get_api_key()
    
    if not api_key:
        yield "⚠️ Configuration incomplète : L'administrateur n'a pas configuré la clé GROQ_API_KEY dans les Secrets."
        return

    history = history or []

    # Personnalisation de l'accueil pour l'administrateur
    est_admin = st.session_state.get("is_admin", False)
    nom_role = "mon Créateur et Développeur" if est_admin else (prenom if prenom else 'un ami')

    system_instruction = (
        "Tu es Floreina, une IA conversationnelle polyvalente, amicale et experte.\n"
        "1. PARLE AVEC LES GENS : Sois chaleureuse, pose des questions, sois naturelle.\n"
        "2. PROPOSER DES SOLUTIONS : Donne des plans d'action clairs, des étapes logiques.\n"
        "3. TROUVER DES RÉPONSES : Réponds précisément à tout (code, calculs, rédaction, culture).\n"
        "Réponds toujours directement en français de manière fluide.\n\n"
        f"Tu discutes actuellement avec {nom_role}. "
        f"Nous sommes le {datetime.datetime.now().strftime('%d/%m/%Y à %H:%M')}."
    )

    web_context = ""
    mots_cles = ["météo", "actu", "aujourd'hui", "nouvelles", "score"]
    if any(kw in text.lower() for kw in mots_cles):
        web_context = web_search_context(text)

    # Connexion à Groq (via l'interface compatible OpenAI)
    if OpenAI:
        try:
            # On configure le client OpenAI pour pointer vers l'adresse internet de Groq
            client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=api_key
            )
            
            messages = [{"role": "system", "content": system_instruction}]
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
            
            prompt_final = text
            if web_context:
                prompt_final = f"[Données Web en temps réel] :\n{web_context}\n\nRequête : {text}"
            messages.append({"role": "user", "content": prompt_final})

            # Appel du modèle Llama 3 ultra-rapide hébergé chez Groq
            response_stream = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.7,
                stream=True
            )
            for chunk in response_stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"Erreur technique Groq : {str(e)}"
    else:
        yield "Erreur : La bibliothèque 'openai' est manquante dans votre environnement."


# --- INTERFACE GRAPHIQUE STREAMLIT ---
st.title("Floreina IA 🤖✨")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_usage_count" not in st.session_state:
    st.session_state.user_usage_count = 0
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

# Barre latérale
with st.sidebar:
    st.subheader("🔑 Espace Connexion")
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

# Entrée utilisateur
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
