# ai_provider.py
import os

def ai_enabled() -> bool:
    """
    Interruptor de segurança:
    - AI_ENABLED=0  -> IA desligada
    - AI_ENABLED=1  -> IA ligada
    """
    return os.environ.get("AI_ENABLED", "0") == "1"


def call_ai(system_prompt: str, user_prompt: str, context: str = "") -> str:
    """
    Versão segura (TESTE):
    - Não chama nenhum serviço externo
    - Só devolve uma resposta “mock” para validar integração sem quebrar o app
    """
    if not ai_enabled():
        return "🐾 A Vinca ainda está desligada por segurança (AI_ENABLED=0)."

    text = user_prompt.lower().strip()

    # respostas mock só pra testar a experiência
    if "chocolate" in text:
        return (
            "⚠️ Chocolate é perigoso para cães e gatos.\n"
            "Se foi ingerido, especialmente por pets pequenos, o mais seguro é contatar um veterinário o quanto antes."
        )

    if "uva" in text or "passa" in text:
        return (
            "⚠️ Uva e uva-passa podem ser perigosas para cães.\n"
            "Se o pet comeu, o ideal é falar com um veterinário imediatamente."
        )

    if "pode comer" in text:
        return (
            "Depende do alimento 😄🐾\n"
            "Me diga qual é (ex.: “cachorro pode comer banana?”) e eu te ajudo com cuidado."
        )

    if "quanto tempo vive" in text or "vive" in text:
        return (
            "Isso varia por espécie, raça, porte e cuidados 🐶🐱\n"
            "Se você me disser se é cão ou gato e o porte, eu te dou uma estimativa e fatores que influenciam."
        )

    if "vacina" in text or "última vacina" in text:
        return (
            "Eu posso te ajudar com vacinas 💉🐾\n"
            "Mas só consigo dizer a *última vacina da Mel* se isso estiver registrado no app."
        )

    return (
        "Oi! Eu sou a Vinca 🐾😄\n"
        "Me pergunte algo como: “cachorro pode comer uva?”, “gato pode comer atum?”, "
        "ou “curiosidades sobre cães”."
    )
