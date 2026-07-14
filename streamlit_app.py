import datetime
import os
import random
import re
from typing import Dict, List
from urllib.parse import unquote, urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - optional dependency
    genai = None
    types = None

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None


def extract_name(user_input: str):
    text = user_input.strip().lower()
    patterns = [
        r"je m'appelle\s+([a-zà-ÿ'-]+)",
        r"mon nom est\s+([a-zà-ÿ'-]+)",
        r"appelle-moi\s+([a-zà-ÿ'-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().capitalize()
    return None


def extract_profile_context(user_input: str, profile: Dict | None = None):
    profile = dict(profile or {})
    text = user_input.strip()
    lower_text = text.lower()

    if any(keyword in lower_text for keyword in ["j'aime", "j'adore", "je suis passionné", "je kiffe"]):
        match = re.search(r"(?:j'aime|j'adore|je suis passionné(?:e)? de|je kiffe)\s+(.+?)(?:\.|,|$)", lower_text)
        if match:
            interest = match.group(1).strip().replace("de ", "")
            if interest:
                profile.setdefault("interests", [])
                if interest not in profile["interests"]:
                    profile["interests"].append(interest)

    if any(keyword in lower_text for keyword in ["j'étudie", "j'apprends", "je travaille sur", "je veux apprendre", "je souhaite apprendre"]):
        match = re.search(r"(?:j'étudie|j'apprends|je travaille sur|je veux apprendre|je souhaite apprendre)\s+(.+?)(?:\.|,|$)", lower_text)
        if match:
            goal = match.group(1).strip()
            if goal:
                profile.setdefault("goals", [])
                if goal not in profile["goals"]:
                    profile["goals"].append(goal)

    if any(keyword in lower_text for keyword in ["je veux", "j'aimerais", "je souhaite", "je cherche"]):
        match = re.search(r"(?:je veux|j'aimerais|je souhaite|je cherche)\s+(.+?)(?:\.|,|$)", lower_text)
        if match:
            goal = match.group(1).strip()
            if goal:
                profile.setdefault("goals", [])
                if goal not in profile["goals"]:
                    profile["goals"].append(goal)

    return profile


def summarize_profile(profile: Dict | None = None):
    profile = profile or {}
    parts = []
    if profile.get("name"):
        parts.append(f"tu te prénommes {profile['name']}")
    if profile.get("interests"):
        interests = ", ".join(profile["interests"][:2])
        parts.append(f"tu aimes {interests}")
    if profile.get("goals"):
        goals = ", ".join(profile["goals"][:2])
        parts.append(f"tu veux {goals}")
    return "; ".join(parts)


def get_api_key():
    if "gemini_api_key" in st.session_state and st.session_state.gemini_api_key:
        return st.session_state.gemini_api_key

    env_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key

    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None


def clean_source_url(href: str):
    if not href:
        return ""
    cleaned = href.strip()
    if cleaned.startswith("//"):
        cleaned = f"https:{cleaned}"
    if "uddg=" in cleaned:
        try:
            parsed = urlparse(cleaned)
            query = parsed.query
            for part in query.split("&"):
                if part.startswith("uddg="):
                    decoded = unquote(part.split("=", 1)[1])
                    if decoded.startswith("http"):
                        return decoded
        except Exception:
            pass
    return cleaned


def web_search_context(query: str):
    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        snippets = []
        for link in soup.select("a.result__a")[:3]:
            title = link.get_text(" ", strip=True)
            href = link.get("href")
            if title and href:
                snippets.append(f"- {title} ({clean_source_url(href)})")
        return "\n".join(snippets)
    except Exception:
        return ""


def web_search_answer(query: str):
    try:
        url = "https://duckduckgo.com/html/"
        params = {"q": query}
        response = requests.get(url, params=params, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for link in soup.select("a.result__a")[:5]:
            title = link.get_text(" ", strip=True)
            href = link.get("href")
            if title and href:
                results.append((title, href))

        if not results:
            return None

        snippets = []
        for title, href in results:
            try:
                page_response = requests.get(href, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                page_response.raise_for_status()
                page_soup = BeautifulSoup(page_response.text, "html.parser")
                paragraphs = [p.get_text(" ", strip=True) for p in page_soup.select("p") if p.get_text(" ", strip=True)]
                text = " ".join(paragraphs[:3])
                if len(text) > 80:
                    snippets.append((title, text, href))
            except Exception:
                continue

        if not snippets:
            title, href = results[0]
            clean_href = clean_source_url(href)
            return f"D’après les informations disponibles, {title}. Source : {clean_href}"

        title, text, href = snippets[0]
        short_text = " ".join(text.split()[:90])
        clean_text = short_text.rstrip(". ")
        clean_href = clean_source_url(href)
        return f"{clean_text}. Source : {clean_href}"
    except Exception:
        return None


def stream_assistant_reply(user_input: str, prenom=None, history=None):
    text = (user_input or "").strip()
    if not text:
        yield "Écrivez quelque chose pour commencer."
        return

    api_key = get_api_key()
    if not api_key:
        yield "⚠️ Configuration incomplète : L'administrateur n'a pas configuré la clé API sur le serveur."
        return

    history = history or []
    system_instruction = (
        "Tu es Floreina, une IA conversationnelle française, amicale et utile. "
        "Réponds avec chaleur, clarté et des conseils concrets."
    )

    web_context = ""
    if any(keyword in text.lower() for keyword in ["météo", "actu", "aujourd'hui", "nouvelles", "score"]):
        web_context = web_search_context(text)

    prompt_final = text if not web_context else f"[Données Web] :\n{web_context}\n\nRequête : {text}"

    if genai and types and ("gemini" in api_key.lower() or "google" in api_key.lower() or len(api_key) > 30):
        try:
            client = genai.Client(api_key=api_key)
            contents = []
            for msg in history:
                role = "user" if msg.get("role") == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.get("content", ""))]))
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt_final)]))
            response_stream = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.7),
            )
            for chunk in response_stream:
                if getattr(chunk, "text", None):
                    yield chunk.text
            return
        except Exception as exc:
            yield f"Erreur technique : {exc}"
            return

    if OpenAI:
        try:
            client = OpenAI(api_key=api_key)
            messages = [{"role": "system", "content": system_instruction}]
            for msg in history:
                if isinstance(msg.get("content"), str):
                    messages.append({"role": msg.get("role", "user"), "content": msg["content"]})
            messages.append({"role": "user", "content": prompt_final})
            response_stream = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
                stream=True,
            )
            for chunk in response_stream:
                content = getattr(getattr(chunk, "choices", [None])[0], "delta", None)
                if content and getattr(content, "content", None):
                    yield content.content
            return
        except Exception as exc:
            yield f"Erreur technique : {exc}"
            return

    yield build_assistant_reply(text, prenom=prenom, history=history, mode="general")


def build_assistant_reply(user_input: str, prenom=None, client=None, history=None, mode="general", profile=None):
    text = user_input.strip()
    history = history or []

    if not text:
        return "Écrivez quelque chose pour commencer."

    lower_text = text.lower()
    profile = dict(profile or {})
    if prenom:
        profile["name"] = prenom

    for item in history:
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            profile = extract_profile_context(item["content"], profile)
    profile = extract_profile_context(text, profile)
    profile_summary = summarize_profile(profile)

    if mode == "premium":
        greeting_prefix = f"Bonjour {prenom}" if prenom else "Bonjour"
        if any(keyword in lower_text for keyword in ["bonjour", "salut", "hello", "bonsoir"]):
            memory_note = f" J’ai noté que {profile_summary}." if profile_summary else ""
            return f"{greeting_prefix} ! Je suis Floreina Premium, à votre écoute.✨{memory_note} Je peux être directe, chaleureuse et très utile."

        if any(keyword in lower_text for keyword in ["merci", "thanks", "thank you"]):
            return f"Avec plaisir{f' {prenom}' if prenom else ''} ! Je reste à votre disposition avec un ton plus naturel et plus pro."

        if any(keyword in lower_text for keyword in ["qui es tu", "présente toi", "tu es qui"]):
            return "Je suis Floreina Premium : votre assistant conversationnel français, attentif, clair et capable de mémoriser vos centres d’intérêt pour mieux vous aider."

        if any(keyword in lower_text for keyword in ["heure", "date", "quel jour"]):
            now = datetime.datetime.now()
            if "heure" in lower_text:
                return f"Il est actuellement {now.strftime('%H:%M')}."
            return f"Nous sommes le {now.strftime('%d/%m/%Y')}"

        if any(keyword in lower_text for keyword in ["blague", "rigole", "joke"]):
            return "Pourquoi les programmeurs aiment-ils le café ? Parce qu’il a un excellent byte. ☕"

        if profile_summary:
            return (
                f"Je vois que {profile_summary}. "
                "Je peux t’accompagner avec un style plus fluide, plus personnel et plus efficace. "
                "Pose-moi une question précise et je te répondrai avec clarté."
            )

    if any(keyword in lower_text for keyword in ["bonjour", "salut", "hello", "bonsoir"]):
        nom = f", {prenom}" if prenom else ""
        return f"Bonjour{nom} ! Floreina est là pour vous aider avec clarté et chaleur. ✨"

    if "je m'appelle" in lower_text or "mon nom est" in lower_text or "appelle-moi" in lower_text:
        name = extract_name(user_input)
        if name:
            return f"Enchanté {name} ! Je retiens votre prénom et je m’en souviendrai pour la suite. 😉"

    if any(keyword in lower_text for keyword in ["qui es tu", "présente toi", "tu es qui"]):
        return "Je suis Floreina, votre mini-IA amicale, utile et attentive, conçue pour vous aider dans de nombreux sujets."

    if any(keyword in lower_text for keyword in ["merci", "thanks", "thank you"]):
        return "Avec plaisir ! Je reste à votre disposition pour la suite."

    if any(keyword in lower_text for keyword in ["aide", "help", "que peux-tu faire"]):
        return "Je peux vous saluer, retenir votre prénom, répondre à des questions simples, lancer un pile ou face, raconter une blague, expliquer des sujets généraux et répondre à plusieurs questions courantes."

    if any(keyword in lower_text for keyword in ["heure", "date", "quel jour"]):
        now = datetime.datetime.now()
        if "heure" in lower_text:
            return f"Il est actuellement {now.strftime('%H:%M')}."
        return f"Nous sommes le {now.strftime('%d/%m/%Y')}"

    if any(keyword in lower_text for keyword in ["pile", "face", "lance une pièce"]):
        return f"🪙 Pièce lancée : c’est tombé sur {random.choice(['Pile', 'Face'])} !"

    if any(keyword in lower_text for keyword in ["boule", "magique", "oracle", "devine"]):
        responses = [
            "Oui absolument ! 🌌",
            "Le doute plane... 🤔",
            "Mes circuits voient un petit bug. ❌",
            "Redemande plus tard avec une question plus précise. 🔋",
        ]
        return f"🔮 La Boule Magique répond : {random.choice(responses)}"

    if any(keyword in lower_text for keyword in ["blague", "rigole", "joke"]):
        return "Pourquoi les programmeurs aiment-ils le café ? Parce qu’il a un excellent byte. ☕"

    if any(keyword in lower_text for keyword in ["résume", "résumer", "synopsis"]):
        return "Je peux vous aider à résumer un texte, mais pour cela il me faut le contenu à résumer."

    if mode == "geographie":
        geography_answers = {
            "continent": "Les continents principaux sont l'Afrique, l'Antarctique, l'Asie, l'Europe, l'Amérique du Nord, l'Amérique du Sud, l'Océanie.",
            "océan": "Les cinq océans sont l'océan Pacifique, l'océan Atlantique, l'océan Indien, l'océan Arctique et l'océan Austral.",
            "montagne la plus haute": "L'Everest est la plus haute montagne du monde.",
            "plus grand désert": "Le Sahara est le plus grand désert chaud du monde.",
            "plus grand pays": "Le plus grand pays du monde par superficie est la Russie.",
            "plus petit pays": "Le plus petit pays du monde est le Vatican.",
            "pays francophone": "Des pays francophones connus sont la France, le Canada, la Belgique, la Suisse, le Sénégal et le Maroc.",
        }
        for question, answer in geography_answers.items():
            if question in lower_text:
                return answer
        if any(keyword in lower_text for keyword in ["pays", "continent", "océan", "montagne", "desert", "géographie"]):
            return "Je peux vous aider en géographie avec des questions sur les continents, les océans, les pays et les capitales."

    if mode == "education":
        education_answers = {
            "definition de l'ecole": "L'école est un lieu d'apprentissage où l'on acquiert des connaissances, des compétences et des valeurs.",
            "definition du savoir": "Le savoir, c'est l'ensemble des connaissances acquises par l'apprentissage et l'expérience.",
            "definition de l'apprentissage": "L'apprentissage est le processus par lequel on acquiert de nouvelles connaissances ou compétences.",
            "definition de la méthode": "Une méthode est une manière organisée d'accomplir une tâche ou d'apprendre.",
            "importance de l'education": "L'éducation permet d'acquérir des connaissances, de développer la pensée critique et d'améliorer la vie personnelle et sociale.",
        }
        for question, answer in education_answers.items():
            if question in lower_text:
                return answer
        if any(keyword in lower_text for keyword in ["éducation", "apprendre", "étudier", "cours", "school", "école"]):
            return "Je peux vous aider sur l'éducation, l'apprentissage, les méthodes d'étude et les définitions de base."

    knowledge_answers = {
        "capitale du sénégal": "La capitale du Sénégal est Dakar.",
        "capitale du mali": "La capitale du Mali est Bamako.",
        "capitale de la france": "La capitale de la France est Paris.",
        "capitale du canada": "La capitale du Canada est Ottawa.",
        "capitale du maroc": "La capitale du Maroc est Rabat.",
        "capitale de la cote d'ivoire": "La capitale de la Côte d’Ivoire est Yamoussoukro.",
        "capitale du burkina faso": "La capitale du Burkina Faso est Ouagadougou.",
        "capitale du benin": "La capitale du Bénin est Porto-Novo.",
        "capitale du gabon": "La capitale du Gabon est Libreville.",
        "capitale de la guinée": "La capitale de la Guinée est Conakry.",
        "capitale du cameroun": "La capitale du Cameroun est Yaoundé.",
        "capitale du congo": "La capitale du Congo est Brazzaville.",
        "capitale du tchad": "La capitale du Tchad est N'Djaména.",
        "capitale de la tunisie": "La capitale de la Tunisie est Tunis.",
        "capitale de l'algérie": "La capitale de l’Algérie est Alger.",
        "capitale de l'egypte": "La capitale de l’Égypte est Le Caire.",
        "capitale du niger": "La capitale du Niger est Niamey.",
        "capitale de la cote d'ivoire": "La capitale de la Côte d’Ivoire est Yamoussoukro.",
        "capitale du mauritanie": "La capitale de la Mauritanie est Nouakchott.",
        "capitale du guinée bissau": "La capitale de la Guinée-Bissau est Bissau.",
        "capitale du togo": "La capitale du Togo est Lomé.",
        "capitale du bénin": "La capitale du Bénin est Porto-Novo.",
        "capitale de la république démocratique du congo": "La capitale de la République démocratique du Congo est Kinshasa.",
        "capitale de la république du congo": "La capitale de la République du Congo est Brazzaville.",
        "capitale du rwanda": "La capitale du Rwanda est Kigali.",
        "capitale du burundi": "La capitale du Burundi est Gitega.",
        "capitale de la madagascar": "La capitale de Madagascar est Antananarivo.",
        "capitale de la djibouti": "La capitale de Djibouti est Djibouti.",
        "capitale de l'ethiopie": "La capitale de l’Éthiopie est Addis-Abeba.",
        "capitale du kenya": "La capitale du Kenya est Nairobi.",
        "capitale de l'uganda": "La capitale de l’Ouganda est Kampala.",
        "capitale du tanzania": "La capitale de la Tanzanie est Dodoma.",
        "capitale du zimbabwe": "La capitale du Zimbabwe est Harare.",
        "capitale de la zambie": "La capitale de la Zambie est Lusaka.",
        "capitale du botswana": "La capitale du Botswana est Gaborone.",
        "capitale de la namibie": "La capitale de la Namibie est Windhoek.",
        "capitale du sud afrique": "La capitale de l’Afrique du Sud est Pretoria, avec le Parlement à Cape Town et la justice à Bloemfontein.",
        "capitale de l'angleterre": "La capitale de l’Angleterre est Londres.",
        "capitale de l'espagne": "La capitale de l’Espagne est Madrid.",
        "capitale de l'italie": "La capitale de l’Italie est Rome.",
        "capitale de l'allemagne": "La capitale de l’Allemagne est Berlin.",
        "capitale du portugal": "La capitale du Portugal est Lisbonne.",
        "capitale de la belgique": "La capitale de la Belgique est Bruxelles.",
        "capitale des pays bas": "La capitale des Pays-Bas est Amsterdam.",
        "capitale de la suisse": "La capitale de la Suisse est Berne.",
        "capitale de l'autriche": "La capitale de l’Autriche est Vienne.",
        "capitale de la suède": "La capitale de la Suède est Stockholm.",
        "capitale de la norvège": "La capitale de la Norvège est Oslo.",
        "capitale du danemark": "La capitale du Danemark est Copenhague.",
        "capitale de la finlande": "La capitale de la Finlande est Helsinki.",
        "capitale de la pologne": "La capitale de la Pologne est Varsovie.",
        "capitale de la grece": "La capitale de la Grèce est Athènes.",
        "capitale de la turquie": "La capitale de la Turquie est Ankara.",
        "capitale de la russie": "La capitale de la Russie est Moscou.",
        "capitale de la chine": "La capitale de la Chine est Pékin.",
        "capitale du japon": "La capitale du Japon est Tokyo.",
        "capitale de l'inde": "La capitale de l’Inde est New Delhi.",
        "capitale de la corée du sud": "La capitale de la Corée du Sud est Séoul.",
        "capitale de la corée du nord": "La capitale de la Corée du Nord est Pyongyang.",
        "capitale de l'australie": "La capitale de l’Australie est Canberra.",
        "capitale de la nouvelle zélande": "La capitale de la Nouvelle-Zélande est Wellington.",
        "capitale du mexique": "La capitale du Mexique est Mexico.",
        "capitale des etats unis": "La capitale des États-Unis est Washington, D.C.",
        "capitale du brésil": "La capitale du Brésil est Brasilia.",
        "capitale de l'argentine": "La capitale de l’Argentine est Buenos Aires.",
        "capitale du chile": "La capitale du Chili est Santiago.",
        "capitale de la colombie": "La capitale de la Colombie est Bogota.",
        "capitale du perou": "La capitale du Pérou est Lima.",
        "capitale de la bolivie": "La capitale de la Bolivie est La Paz et Sucre.",
        "capitale de l'ecuador": "La capitale de l’Équateur est Quito.",
        "capitale du paraguay": "La capitale du Paraguay est Asuncion.",
        "capitale de l'uruguay": "La capitale de l’Uruguay est Montevideo.",
        "capitale du venezuela": "La capitale du Venezuela est Caracas.",
        "capitale du panama": "La capitale du Panama est Panama.",
        "capitale du costa rica": "La capitale du Costa Rica est San José.",
        "capitale du guatemala": "La capitale du Guatemala est Guatemala City.",
        "capitale du cuba": "La capitale de Cuba est La Havane.",
        "capitale de la jamaïque": "La capitale de la Jamaïque est Kingston.",
        "capitale d'haïti": "La capitale d’Haïti est Port-au-Prince.",
        "capitale du nigeria": "La capitale du Nigeria est Abuja.",
        "capitale du ghana": "La capitale du Ghana est Accra.",
        "capitale de la cote d'ivoire": "La capitale de la Côte d’Ivoire est Yamoussoukro.",
        "capitale du sénégal": "La capitale du Sénégal est Dakar.",
        "capitale du sud afrique": "La capitale de l’Afrique du Sud est Pretoria, avec le Parlement à Cape Town et la justice à Bloemfontein.",
        "capital de la france": "La capitale de la France est Paris.",
        "capital du sénégal": "La capitale du Sénégal est Dakar.",
        "capital du canada": "La capitale du Canada est Ottawa.",
        "capital de l'algérie": "La capitale de l’Algérie est Alger.",
    }

    for question, answer in knowledge_answers.items():
        if question in lower_text:
            return answer

    if any(keyword in lower_text for keyword in ["quelle est la capitale", "capitale de", "capital de"]):
        return "Je peux répondre à beaucoup de capitales de pays. Par exemple : Dakar pour le Sénégal, Paris pour la France, Rabat pour le Maroc, Abuja pour le Nigeria ou Tokyo pour le Japon."

    if any(keyword in lower_text for keyword in ["comment", "pourquoi", "explique", "quoi", "qu'est-ce"]):
        return "Je peux vous aider à expliquer des idées simples, répondre à des questions courantes et vous guider pas à pas. Essayez par exemple : « Quelle est la capitale du Sénégal ? » ou « Explique-moi le Python »."

    web_result = web_search_answer(user_input)
    if web_result:
        return web_result

    if client:
        try:
            context_history = "\n".join(
                f"{item['role']}: {item['content']}" for item in history[-6:]
            )
            context = (
                "Tu t'appelles Floreina, une mini-IA française, amicale, utile et naturelle. "
                f"L'utilisateur s'appelle {prenom if prenom else 'mon ami'}. "
                f"Voici l'historique récent : {context_history}. "
                f"Réponds à sa demande de manière claire, concise, structurée et en français : {user_input}"
            )
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": "Tu es Floreina, une assistante française utile et naturelle."}, {"role": "user", "content": context}],
                temperature=0.3,
            )
            return response.choices[0].message.content
        except Exception:
            pass

    return (
        "J’ai compris votre demande. "
        "Je peux déjà vous aider pour les salutations, votre prénom, l’heure, les blagues, les capitales et les questions simples."
    )


def main():
    st.set_page_config(page_title="Floreina IA Premium", page_icon="🤖")
    st.title("🤖 Floreina Premium")
    st.caption("Assistant conversationnel premium, naturel, personnel et ultra utile.")

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Bonjour ! Je suis Floreina Premium. Dites-moi votre prénom, votre objectif ou une question, et je vous répondrai avec beaucoup plus de naturel et de précision."}
        ]
    if "prenom" not in st.session_state:
        st.session_state.prenom = None
    if "gemini_api_key" not in st.session_state:
        st.session_state.gemini_api_key = ""
    if "profile" not in st.session_state:
        st.session_state.profile = {}

    with st.sidebar:
        st.header("Configuration")
        st.info("Floreina fonctionne déjà localement, mais l’IA externe est activée automatiquement si une clé est disponible.")
        st.markdown("- Réponses plus naturelles")
        st.markdown("- Mémoire de profil")
        st.markdown("- Style premium")
        mode = st.radio(
            "Mode expert",
            options=["general", "geographie", "education", "premium"],
            format_func=lambda value: {
                "general": "Général",
                "geographie": "Géographie",
                "education": "Éducation",
                "premium": "Premium",
            }[value],
            index=3,
        )

        if st.session_state.profile:
            st.subheader("Mémoire active")
            summary = summarize_profile(st.session_state.profile)
            st.caption(summary if summary else "Aucune information mémorisée pour l’instant.")

    api_key = get_api_key()
    client = None
    if api_key:
        try:
            client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        except Exception:
            client = None

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    if user_input := st.chat_input("Posez votre question à Floreina..."):
        with st.chat_message("user"):
            st.write(user_input)
        st.session_state.messages.append({"role": "user", "content": user_input})

        new_name = extract_name(user_input)
        if new_name:
            st.session_state.prenom = new_name

        st.session_state.profile = extract_profile_context(user_input, st.session_state.profile)
        if st.session_state.prenom:
            st.session_state.profile["name"] = st.session_state.prenom

        response = build_assistant_reply(
            user_input,
            st.session_state.prenom,
            client,
            st.session_state.messages,
            mode,
            st.session_state.profile,
        )
        if response and len(response) > 220:
            response = response[:220].rstrip() + "..."

        with st.chat_message("assistant"):
            st.write(response)
        st.session_state.messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
