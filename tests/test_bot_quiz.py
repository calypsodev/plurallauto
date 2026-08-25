import os

os.environ.setdefault("NVIDIA_API_KEY", "test-key")

import bot_quiz


def test_normaliza_expressao_matematica():
    assert bot_quiz.normalizar_texto_matematico("5πk²/24") == "5pi*k^2/24"
    assert bot_quiz.normalizar_texto_matematico("3πk²/8") == "3pi*k^2/8"


def test_busca_opcao_por_expressao():
    opcoes = [
        {"texto": "πk²/2", "locator": object()},
        {"texto": "πk²/6", "locator": object()},
        {"texto": "πk²/12", "locator": object()},
        {"texto": "3πk²/8", "locator": object()},
        {"texto": "5πk²/24", "locator": object()},
    ]

    match = bot_quiz.buscar_opcao_correspondente("RESPOSTA_FINAL: 5πk²/24", opcoes)
    assert match is not None
    assert match["texto"] == "5πk²/24"

    match_num = bot_quiz.buscar_opcao_correspondente("RESPOSTA_FINAL: 5", opcoes)
    assert match_num is not None
    assert match_num["texto"] == "5πk²/24"


def test_normaliza_padrao_plurall_com_risco_e_fragmentacao():
    assert bot_quiz.normalizar_texto_matematico("πk26") == "pi*k^2/6"
    assert bot_quiz.normalizar_texto_matematico("5πk224") == "5pi*k^2/24"

    opcoes = [
        {"texto": "πk²/2 Riscar", "locator": object()},
        {"texto": "πk26 Riscar", "locator": object()},
        {"texto": "πk212 Riscar", "locator": object()},
        {"texto": "3πk28 Riscar", "locator": object()},
        {"texto": "5πk224 Riscar", "locator": object()},
    ]
    filtradas = bot_quiz.filtrar_opcoes_questao(opcoes)
    assert len(filtradas) == 5
    assert filtradas[4]["texto"] == "5πk²/24"


def test_clica_no_ancestre_interativo_quando_o_texto_nao_e_o_botao():
    class FakeLocator:
        def __init__(self):
            self.click_calls = []

        def click(self, force=False):
            self.click_calls.append(force)
            return None

        def evaluate(self, script):
            if "closest('button')" in script:
                return True
            return False

    locator = FakeLocator()
    assert bot_quiz.clicar_elemento_robusto(locator) is True
    assert locator.click_calls == [False] or locator.click_calls == [False, True]
