import streamlit_app as app
from streamlit_app import build_assistant_reply, extract_name


def test_greeting_uses_name_when_available():
    reply = build_assistant_reply("bonjour", "Alice")
    assert "Bonjour" in reply
    assert "Alice" in reply


def test_name_extraction_from_statement():
    assert extract_name("Je m'appelle Alice") == "Alice"
    assert extract_name("je m'appelle marie") == "Marie"


def test_history_is_accepted_without_breaking():
    reply = build_assistant_reply("dis moi une blague", history=[{"role": "user", "content": "bonjour"}])
    assert "Pourquoi" in reply or "byte" in reply


def test_general_question_gets_helpful_local_answer():
    reply = build_assistant_reply("Quelle est la capitale du Sénégal ?")
    assert "Dakar" in reply or "capitale" in reply.lower()


def test_geography_mode_handles_geographic_questions():
    reply = build_assistant_reply("Quel est le plus grand désert du monde ?", mode="geographie")
    assert "Sahara" in reply


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_web_search_answer_uses_polished_response_style(monkeypatch):
    html = """
    <html><body>
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fguide">Guide pratique</a>
        <div class="result__snippet">Un résumé utile et précis trouvé sur la page.</div>
    </body></html>
    """

    def fake_get(url, params=None, timeout=10, headers=None):
        if "duckduckgo.com/html/" in url:
            return FakeResponse(html)
        return FakeResponse("<html><body><p>Contenu utile.</p></body></html>")

    monkeypatch.setattr(app.requests, "get", fake_get)
    reply = app.web_search_answer("test")

    assert "D’après les informations disponibles" in reply or "Source :" in reply
    assert "J’ai trouvé une information utile" not in reply
    assert "https://example.com/guide" in reply
    assert "//duckduckgo.com" not in reply


def test_premium_mode_uses_memory_and_personalization():
    reply = build_assistant_reply(
        "J'aime le cinéma et j'étudie l'histoire",
        prenom="Alice",
        history=[{"role": "user", "content": "bonjour"}],
        mode="premium",
    )
    assert "Alice" in reply or "cinéma" in reply.lower() or "histoire" in reply.lower()


def test_streaming_reply_without_api_key_returns_guidance():
    chunks = list(app.stream_assistant_reply("bonjour"))
    assert chunks
    assert any("Configuration incomplète" in chunk for chunk in chunks)
