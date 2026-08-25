import os
import sys
import time
import json
import re
import base64
import html
import unicodedata
import requests
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, Locator

load_dotenv(override=True)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_API_URL = os.getenv("NVIDIA_API_URL", "https://integrate.api.nvidia.com/v1/chat/completions")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.2-90b-vision-instruct")
NVIDIA_API_TIMEOUT = int(os.getenv("NVIDIA_API_TIMEOUT", "120"))
NVIDIA_VERIFY_SSL = os.getenv("NVIDIA_VERIFY_SSL", "true").lower() == "true"
CLICAR_VISUALIZAR = os.getenv("CLICAR_VISUALIZAR", "true").lower() == "true"
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
PLURALL_LOGIN_URL = os.getenv("PLURALL_LOGIN_URL", "https://login.plurall.net/")
PLURALL_EMAIL = os.getenv("PLURALL_EMAIL")
PLURALL_SENHA = os.getenv("PLURALL_SENHA")
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

if not NVIDIA_API_KEY:
    print("Erro: NVIDIA_API_KEY nao definida. Copie .env.example para .env e configure sua chave.")
    sys.exit(1)

os.makedirs("debug", exist_ok=True)


class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"


def log(msg, color=Colors.CYAN):
    print(f"{color}{msg}{Colors.RESET}")


def documentos_da_atividade(page: Page) -> list:
    frames_atividade = [
        frame for frame in page.frames
        if "templates.plurall.net" in frame.url
    ]
    return frames_atividade or [page]


def extrair_texto_pagina(page: Page) -> str:
    try:
        # Espera o React renderizar
        time.sleep(2)
        seletores_conteudo = [
            "#container-hold-content",
            "main",
            "[aria-label='Conteudo principal']",
            "[role='main']",
            "article",
            ".question",
            ".questao",
            ".quiz",
            ".atividade",
        ]
        documentos = documentos_da_atividade(page)
        candidatos_texto = []
        for documento in documentos:
            for seletor in seletores_conteudo:
                try:
                    loc = documento.locator(seletor).first
                    if loc.count() > 0 and loc.is_visible():
                        texto = loc.inner_text().strip()
                        if len(texto) > 20:
                            candidatos_texto.append(texto)
                except Exception:
                    continue
            try:
                texto_frame = documento.locator("body").inner_text().strip()
                if len(texto_frame) > 20:
                    candidatos_texto.append(texto_frame)
            except Exception:
                continue
        if candidatos_texto:
            return max(candidatos_texto, key=len)

        # Fallback: concatena apenas textos visiveis do documento.
        texto = page.evaluate("""() => {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            const parts = [];
            let node;
            while (node = walker.nextNode()) {
                const parent = node.parentElement;
                if (parent && parent.offsetParent !== null) {
                    const t = node.textContent.trim();
                    if (t && t.length > 1) parts.push(t);
                }
            }
            return parts.join('\\n');
        }""")
        return (texto or '').strip()
    except Exception:
        return ""


def carregar_conteudo_completo(page: Page) -> None:
    for documento in documentos_da_atividade(page):
        try:
            documento.evaluate("""async () => {
                const altura = Math.max(
                    document.body.scrollHeight,
                    document.documentElement.scrollHeight
                );
                window.scrollTo(0, altura);
                await new Promise(resolve => setTimeout(resolve, 800));
                window.scrollTo(0, 0);
            }""")
        except Exception:
            continue
    time.sleep(1)


def extrair_textos_acessiveis(page: Page) -> str:
    textos = []
    documentos = documentos_da_atividade(page)
    for documento in documentos:
        try:
            encontrados = documento.locator(
                "[aria-label], [alt], [title], [value]"
            ).evaluate_all("""elementos => elementos
                .filter(el => el.offsetParent !== null)
                .flatMap(el => [
                    el.getAttribute('aria-label'),
                    el.getAttribute('alt'),
                    el.getAttribute('title'),
                    el.getAttribute('value')
                ])
                .filter(Boolean)""")
            textos.extend(encontrados)
        except Exception:
            continue
    vistos = set()
    return "\n".join(
        texto.strip() for texto in textos
        if texto and texto.strip() and not (texto.strip() in vistos or vistos.add(texto.strip()))
    )


def diagnosticar_frames(page: Page) -> None:
    for indice, frame in enumerate(page.frames):
        try:
            tamanho = len(frame.locator("body").inner_text())
        except Exception:
            tamanho = 0
        log(f"Frame {indice}: url={frame.url} texto={tamanho} caracteres", Colors.CYAN)


def pagina_de_prova_aberta(page: Page) -> bool:
    try:
        if "avaliacoes.plurall.net" in page.url:
            return True
        return page.locator("[data-testid='question-card-0']").count() > 0
    except Exception:
        return False


def localizar_pagina_de_prova(context, pagina_atual: Page) -> Page:
    paginas = [pagina_atual] + [pagina for pagina in context.pages if pagina != pagina_atual]
    for pagina in paginas:
        try:
            if pagina_de_prova_aberta(pagina):
                return pagina
        except Exception:
            continue
    return pagina_atual


def extrair_elementos_clicaveis(page: Page) -> list:
    seletores = [
        "button",
        "a[href]",
        "input[type='submit']",
        "input[type='button']",
        "input[type='radio']",
        "input[type='checkbox']",
        "[role='button']",
        "[role='link']",
        "[role='tab']",
        "[role='option']",
        "[role='menuitem']",
        "[role='radio']",
        "label",
        "[onclick]",
        "[data-test-id]",
        "[data-test-id*='option']",
        "[data-test-id*='answer']",
        "[aria-label*='opcao']",
        "[aria-label*='alternativa']",
        ".css-qcimgz",
        ".css-gu7qiy",
        ".css-nwhws3",
    ]
    elementos = []
    vistos = set()
    documentos = [page] + [frame for frame in page.frames if frame != page.main_frame]
    for documento in documentos:
        try:
            cartoes = documento.locator("[data-testid='answer-card']").all()
            for cartao in cartoes:
                if not cartao.is_visible():
                    continue
                texto = html.unescape(cartao.get_attribute("title") or "").strip()
                if not texto:
                    texto = cartao.inner_text().strip()
                try:
                    identificador = cartao.locator("[data-test-id^='icon-alternative-']").first.get_attribute("data-test-id")
                    if identificador:
                        letra = identificador.rsplit("-", 1)[-1].upper()
                        texto_sem_ruido = re.sub(
                            r"(?i)\b(riscar|clear question|limpar questao)\b", "", texto
                        ).strip()
                        texto = texto_sem_ruido or letra
                except Exception:
                    pass
                if texto and texto not in vistos:
                    vistos.add(texto)
                    elementos.append({
                        "texto": texto.strip(),
                        "seletor": "[data-testid='answer-card']",
                        "tag": "div",
                        "locator": cartao,
                    })
        except Exception:
            pass
        for sel in seletores:
            try:
                locs = documento.locator(sel).all()
                for loc in locs:
                    try:
                        if not loc.is_visible():
                            continue
                        desabilitado = loc.evaluate("""el => {
                            const style = window.getComputedStyle(el);
                            return !!(el.disabled || el.getAttribute('aria-disabled') === 'true' || el.closest('[aria-disabled=\"true\"]') || style.pointerEvents === 'none');
                        }""")
                        if desabilitado:
                            continue
                        txt = loc.inner_text().strip()
                        if not txt:
                            txt = loc.get_attribute("aria-label") or ""
                            txt = txt.strip()
                        if not txt:
                            txt = loc.get_attribute("data-test-id") or ""
                            txt = txt.strip()
                        if not txt:
                            txt = loc.get_attribute("title") or ""
                            txt = txt.strip()
                        if txt and txt not in vistos:
                            vistos.add(txt)
                            tag = loc.evaluate("el => el.tagName.toLowerCase()")
                            elementos.append({
                                "texto": txt,
                                "seletor": sel,
                                "tag": tag,
                                "locator": loc,
                            })
                    except Exception:
                        pass
            except Exception:
                pass
    return elementos


def _reconstruir_opcao_fragmentada(texto: str) -> str:
    if not texto:
        return ""

    texto = unicodedata.normalize("NFKC", texto)
    texto = texto.replace("&#960;", "π").replace("&pi;", "π")
    texto = texto.replace("\u00a0", " ")
    texto = re.sub(r"(?i)\bclear question\b|\briscar\b|\blimpar questao\b", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    match = re.search(r"(?i)(\d*)\s*pi\s*k\s*(\d+)", texto)
    if match:
        coef = match.group(1) or "1"
        numero = match.group(2)
        if len(numero) >= 2:
            if len(numero) > 2:
                exp = numero[0]
                den = numero[1:]
                return f"{coef}pi*k^{exp}/{den}"
            exp = numero[0]
            den = numero[1]
            return f"{coef}pi*k^{exp}/{den}"
        return f"{coef}pi*k^{numero}"

    return texto.strip()


def normalizar_texto_matematico(texto: str) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKC", texto)
    texto = texto.replace("&#960;", "π").replace("&pi;", "π")
    substituicoes = {
        "π": "pi",
        "∏": "pi",
        "²": "^2",
        "³": "^3",
        "¹": "^1",
        "⁴": "^4",
        "⁵": "^5",
        "⁶": "^6",
        "⁷": "^7",
        "⁸": "^8",
        "⁹": "^9",
        "×": "*",
        "÷": "/",
        "−": "-",
        "–": "-",
        "—": "-",
        "·": "*",
    }
    for origem, destino in substituicoes.items():
        texto = texto.replace(origem, destino)
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", "", texto)
    texto = re.sub(r"(?<=\d)pi", "*pi", texto)
    texto = re.sub(r"(?<=\w)pi", "*pi", texto)
    texto = re.sub(r"(?<=\))pi", "*pi", texto)
    texto = re.sub(r"pi\*?k(\d)", r"pi*k^\1", texto)
    texto = re.sub(r"pi\*?k(\d+)", r"pi*k^\1", texto)
    texto = re.sub(r"k\^?(\d+)/(\d+)", r"k^\1/\2", texto)
    texto = texto.strip(".,;:()[]{}<>\"'")
    return texto


def filtrar_opcoes_questao(elementos: list) -> list:
    termos_navegacao = [
        "voltar", "pagina anterior", "inicio", "assistente", "sala de aula",
        "biblioteca", "maestro", "atividade", "simulado", "prova", "conteudo",
        "aula do dia", "menu", "sair", "logout", "configuracao", "pular para",
        "ajuda", "notificacao", "notificacoes", "perfil", "usuario", "aplicativo",
        "meus aplicativos", "more_vert", "help-button", "notification-button",
        "user-button", "apps-button", "handler-open", "icon-", "salvar resposta",
        "responder", "clear question", "riscar", "monitoring-button-exam",
        "--:--:--", "anterior", "próximo", "proximo", "next", "continuar",
        "visualizar", "limpar questao", "marcar", "desmarcar", "cronometro",
        "timer",
    ]
    opcoes = []
    textos_vistos = set()
    for elemento in elementos:
        texto = re.sub(r"\s+", " ", elemento["texto"]).strip()
        if not texto:
            continue

        texto_normal = unicodedata.normalize("NFKD", texto)
        texto_normal = "".join(c for c in texto_normal if not unicodedata.combining(c))
        texto_normal = texto_normal.replace("&nbsp;", " ").replace("&#960;", "π")
        texto_normal = re.sub(r"\s+", " ", texto_normal).strip()
        texto_sem_ruido = re.sub(r"(?i)\b(riscar|clear question|limpar questao)\b", "", texto_normal).strip()
        texto_sem_ruido = re.sub(r"\s+", " ", texto_sem_ruido).strip()
        texto_lower = texto_sem_ruido.lower()

        if elemento["seletor"] == "a[href]":
            continue
        if re.match(r"^quest[aã]o\s*\d*$", texto_lower):
            continue
        if any(termo in texto_lower for termo in termos_navegacao):
            continue

        texto_limpo = _reconstruir_opcao_fragmentada(texto_sem_ruido)
        if not texto_limpo:
            continue

        if not re.search(r"[πpikae]|\d", texto_limpo, re.IGNORECASE) and not re.fullmatch(
            r"[a-e]", texto_limpo.strip(), re.IGNORECASE
        ):
            continue

        texto_padronizado = texto_limpo
        texto_padronizado = texto_padronizado.replace("π", "pi")
        texto_padronizado = re.sub(r"(?i)pi\s*(\d+)", r"pi\1", texto_padronizado)
        texto_padronizado = re.sub(r"(?i)([0-9])\s*pi", r"\1pi", texto_padronizado)
        texto_padronizado = re.sub(r"(?i)k\s*(\d+)", r"k^\1", texto_padronizado)
        texto_padronizado = re.sub(r"(?i)k\^?(\d+)/(\d+)", r"k^\1/\2", texto_padronizado)
        texto_padronizado = re.sub(r"(?i)k\^?(\d+)", r"k^\1", texto_padronizado)

        if texto_padronizado in textos_vistos:
            continue
        textos_vistos.add(texto_padronizado)
        opcoes.append({**elemento, "texto": texto_padronizado})

    opcoes_organizadas = []
    for opcao in opcoes:
        texto = opcao["texto"]
        texto = texto.replace("pi", "π")
        texto = texto.replace("π*k^2/6", "πk²/6")
        texto = texto.replace("π*k^2/12", "πk²/12")
        texto = texto.replace("π*k^2/24", "πk²/24")
        texto = texto.replace("π*k^2/8", "πk²/8")
        texto = texto.replace("π*k^2/2", "πk²/2")
        texto = texto.replace("πk^2", "πk²")
        if texto not in [item["texto"] for item in opcoes_organizadas]:
            opcoes_organizadas.append({**opcao, "texto": texto})

    return opcoes_organizadas


def extrair_campos_texto(page: Page) -> list:
    campos = []
    try:
        documentos = [page] + [frame for frame in page.frames if frame != page.main_frame]
        for documento in documentos:
            inputs = documento.locator(
                "input[type='text'], textarea, [contenteditable='true'], [role='textbox']"
            ).all()
            for inp in inputs:
                try:
                    if not inp.is_visible():
                        continue
                    placeholder = inp.get_attribute("placeholder") or ""
                    name = inp.get_attribute("name") or ""
                    campos.append({
                        "placeholder": placeholder.strip(),
                        "name": name.strip(),
                        "locator": inp,
                    })
                except Exception:
                    pass
    except Exception:
        pass
    return campos


def detectar_botao_proximo(elementos: list) -> dict | None:
    palavras = ["proximo", "próximo", "avancar", "avançar", "next", "continuar", "enviar", "submit", "confirmar", "ok", ">"]
    for el in elementos:
        txt = el["texto"].lower()
        if any(p in txt for p in palavras) or txt in (">", ">>"):
            return el
    return None


def chamar_nvidia(
    texto_pagina: str,
    opcoes: list,
    captura: bytes | None = None,
    tipo_captura: str = "image/png",
) -> str:
    opcoes_txt = "\n".join(
        [f"{indice}. {opcao['texto']}" for indice, opcao in enumerate(opcoes, start=1)]
    ) if opcoes else "(nenhuma opcao detectada)"
    prompt = (
        "Voce e um professor cuidadoso corrigindo uma questao escolar.\n"
        "Ignore menus, datas, links, botoes de navegacao, cabecalho e textos da interface.\n"
        "Leia na imagem o enunciado completo e o texto completo de cada alternativa.\n"
        "Esta pode ser uma questao de matematica: preserve mentalmente sinais, "
        "radicais, fracoes, expoentes, subscritos, angulos, unidades e figuras.\n"
        "Quando o texto do DOM estiver incompleto ou trouxer simbolos faltando, "
        "use a imagem em alta resolucao como fonte principal e nao invente o simbolo.\n"
        "Compare cada alternativa com o enunciado e elimine as incorretas antes de decidir. "
        "Nao escolha pela ordem, pela letra ou por uma suposicao.\n"
        "Determine qual e a resposta correta entre as opcoes fornecidas.\n"
        "Se houver opcoes, responda EXATAMENTE no formato RESPOSTA_FINAL: X, "
        "substituindo X pela letra correta (A, B, C, D ou E) ou, quando a alternativa for "
        "uma expressao matematica, pelo numero correspondente da alternativa (1, 2, 3, 4 ou 5). "
        "Nao escreva mais nada.\n"
        "Se for uma questao dissertativa ou nao houver opcoes, responda com a resposta direta.\n\n"
        f"TEXTO DA PAGINA:\n{texto_pagina}\n\n"
        f"OPCOES ENCONTRADAS:\n{opcoes_txt}\n\n"
        "RESPOSTA:"
    )
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    mensagem = [
        {"type": "text", "text": prompt},
    ]
    if captura:
        imagem_base64 = base64.b64encode(captura).decode("ascii")
        mensagem.append({
            "type": "image_url",
            "image_url": {"url": f"data:{tipo_captura};base64,{imagem_base64}"},
        })
    payload = {
        "model": NVIDIA_MODEL,
        "messages": [
            {"role": "system", "content": "Use o texto e a imagem. Para multipla escolha, responda somente RESPOSTA_FINAL: X."},
            {"role": "user", "content": mensagem},
        ],
        "max_tokens": 200,
        "temperature": 0.1,
    }
    try:
        log(f"Chamando NVIDIA API: {NVIDIA_API_URL} (modelo: {NVIDIA_MODEL})", Colors.YELLOW)
        resp = requests.post(
            NVIDIA_API_URL,
            headers=headers,
            json=payload,
            timeout=NVIDIA_API_TIMEOUT,
            verify=NVIDIA_VERIFY_SSL,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        detalhe = e.response.text[:500] if e.response is not None else str(e)
        log(f"Erro HTTP {status} na NVIDIA API: {detalhe}", Colors.RED)
        return ""
    except (KeyError, IndexError, ValueError) as e:
        log(f"Resposta inesperada da NVIDIA API: {e}", Colors.RED)
        return ""
    except requests.exceptions.RequestException as e:
        log(f"Erro de conexao com a NVIDIA API: {e}", Colors.RED)
        return ""
    
    return ""


def encontrar_e_clicar(page: Page, texto_resposta: str) -> bool:
    if not texto_resposta:
        return False
    texto_lower = texto_resposta.lower().strip()
    elementos = extrair_elementos_clicaveis(page)
    # match exato primeiro
    for el in elementos:
        if el["texto"].lower().strip() == texto_lower:
            try:
                el["locator"].click()
                log(f"Clicado (exato): {el['texto']}", Colors.GREEN)
                return True
            except Exception:
                pass
    # match parcial
    for el in elementos:
        if texto_lower in el["texto"].lower() or el["texto"].lower() in texto_lower:
            try:
                el["locator"].click()
                log(f"Clicado (parcial): {el['texto']}", Colors.GREEN)
                return True
            except Exception:
                pass
    log(f"Nenhum elemento correspondente a '{texto_resposta}' encontrado.", Colors.YELLOW)
    return False


def normalizar_texto_matematico(texto: str) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKC", texto)
    texto = texto.replace("&#960;", "π").replace("&pi;", "π")
    substituicoes = {
        "π": "pi",
        "∏": "pi",
        "²": "^2",
        "³": "^3",
        "¹": "^1",
        "⁴": "^4",
        "⁵": "^5",
        "⁶": "^6",
        "⁷": "^7",
        "⁸": "^8",
        "⁹": "^9",
        "×": "*",
        "÷": "/",
        "−": "-",
        "–": "-",
        "—": "-",
        "·": "*",
    }
    for origem, destino in substituicoes.items():
        texto = texto.replace(origem, destino)
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", "", texto)
    texto = re.sub(r"(?<=\d)pi", "*pi", texto)
    texto = re.sub(r"(?<=\w)pi", "*pi", texto)
    texto = re.sub(r"(?<=\))pi", "*pi", texto)
    texto = re.sub(r"pi\*?k(\d)", r"pi*k^\1", texto)
    texto = re.sub(r"pi\*?k(\d+)", r"pi*k^\1", texto)
    texto = re.sub(r"k\^?(\d+)/(\d+)", r"k^\1/\2", texto)
    texto = texto.strip(".,;:()[]{}<>\"'")
    return texto


def buscar_opcao_correspondente(resposta: str, opcoes: list):
    if not resposta or not opcoes:
        return None

    resposta_limpa = resposta.strip()
    resposta_limpa = re.sub(r"\s+", " ", resposta_limpa)
    resposta_limpa = resposta_limpa.strip("\n\r")

    padrao_resposta = re.search(
        r"(?:resposta(?:\s*_?\s*final)?|alternativa(?:\s*certa)?|opcao(?:\s*certa)?)\s*[:=]?\s*(.+)",
        resposta_limpa,
        re.IGNORECASE,
    )
    if padrao_resposta:
        resposta_limpa = padrao_resposta.group(1).strip()

    resposta_norm = normalizar_texto_matematico(resposta_limpa)
    if not resposta_norm:
        return None

    # Resposta numérica direta: "5" => 5ª alternativa.
    if resposta_norm.isdigit():
        indice = int(resposta_norm) - 1
        if 0 <= indice < len(opcoes):
            return opcoes[indice]

    # Resposta em letra: "a", "b", ...
    if len(resposta_norm) == 1 and resposta_norm in "abcde":
        indice = ord(resposta_norm) - ord("a")
        if 0 <= indice < len(opcoes):
            return opcoes[indice]

    # Resposta em expressão matemática: "5pi*k^2/24" => compara de forma exata.
    for opcao in opcoes:
        texto_norm = normalizar_texto_matematico(opcao["texto"])
        if texto_norm == resposta_norm:
            return opcao

    # Fallback: procura um número explícito no texto da resposta, como "5πk²/24".
    numeros = re.findall(r"\d+", resposta_limpa)
    if numeros:
        ultimo_numero = int(numeros[-1])
        if 1 <= ultimo_numero <= len(opcoes):
            return opcoes[ultimo_numero - 1]

    return None


def clicar_elemento_robusto(locator) -> bool:
    try:
        locator.click(force=True)
        return True
    except Exception:
        pass

    try:
        clicou = locator.evaluate("""
            el => {
                const candidatos = [
                    el,
                    el.closest('button'),
                    el.closest('label'),
                    el.closest('a'),
                    el.closest('[role="button"]'),
                    el.closest('[role="option"]'),
                    el.closest('[role="radio"]'),
                    el.closest('input'),
                ].filter(Boolean);

                const interativo = candidatos.find(item => {
                    if (!item) return false;
                    if (item.disabled || item.getAttribute('aria-disabled') === 'true') return false;
                    const style = window.getComputedStyle(item);
                    if (style.pointerEvents === 'none') return false;
                    return true;
                });

                if (interativo) {
                    interativo.click();
                    return true;
                }

                return false;
            }
        """)
        return bool(clicou)
    except Exception:
        return False


def clicar_opcao_por_indice(page: Page, opcoes: list, resposta: str) -> bool:
    opcao = buscar_opcao_correspondente(resposta, opcoes)
    if opcao is None:
        return False

    try:
        if clicar_elemento_robusto(opcao["locator"]):
            log(f"Alternativa selecionada: {opcao['texto']}", Colors.GREEN)
            return True
    except Exception as e:
        log(f"Erro ao selecionar alternativa: {e}", Colors.RED)

    log(f"Nao foi possivel clicar na alternativa correspondente: {opcao['texto']}", Colors.RED)
    return False


def digitar_resposta(page: Page, texto_resposta: str) -> bool:
    campos = extrair_campos_texto(page)
    if not campos:
        return False
    campo = campos[0]
    try:
        campo["locator"].click()
        campo["locator"].fill("")
        campo["locator"].fill(texto_resposta)
        log(f"Digitado no campo '{campo.get('name') or campo.get('placeholder')}': {texto_resposta}", Colors.GREEN)
        return True
    except Exception as e:
        log(f"Erro ao digitar: {e}", Colors.RED)
        return False


def avancar_questao(page: Page) -> bool:
    elementos = extrair_elementos_clicaveis(page)
    for documento in [page] + [frame for frame in page.frames if frame != page.main_frame]:
        try:
            proximo = documento.locator("[data-test-id='next-question']").first
            if proximo.count() > 0 and proximo.is_visible() and not proximo.is_disabled():
                proximo.click()
                log("Avancando para a proxima questao...", Colors.YELLOW)
                return True
        except Exception:
            pass

    for texto, mensagem in [("Salvar resposta", "Resposta salva."), ("Responder", "Resposta enviada.")]:
        controle = next(
            (elemento for elemento in elementos
             if elemento["texto"].strip().lower() == texto.lower()),
            None,
        )
        if not controle:
            log(f"Nao encontrei o botao '{texto}'.", Colors.RED)
            return False
        try:
            controle["locator"].click()
            log(mensagem, Colors.GREEN)
            time.sleep(0.8)
        except Exception as e:
            log(f"Erro ao clicar em '{texto}': {e}", Colors.RED)
            return False

    documentos = [page] + [frame for frame in page.frames if frame != page.main_frame]
    for documento in documentos:
        seta = documento.locator(
            "md-icon.activity-nav-btn[data-ng-click='onClickRight()']"
        ).first
        try:
            if seta.count() > 0 and seta.is_visible():
                seta.click()
                log("Avancando para a proxima questao...", Colors.YELLOW)
                if CLICAR_VISUALIZAR:
                    for _ in range(10):
                        time.sleep(0.5)
                        documentos_popup = [page] + [
                            frame for frame in page.frames if frame != page.main_frame
                        ]
                        for documento_popup in documentos_popup:
                            visualizar = documento_popup.get_by_text(
                                "Visualizar", exact=True
                            ).first
                            try:
                                if visualizar.count() > 0 and visualizar.is_visible():
                                    visualizar.click()
                                    log("Clicado em Visualizar.", Colors.GREEN)
                                    return True
                            except Exception:
                                pass
                    log("Nao encontrei o botao 'Visualizar' no popup.", Colors.YELLOW)
                    log("Continuando sem clicar em Visualizar.", Colors.YELLOW)
                return True
        except Exception as e:
            log(f"Erro ao clicar na seta da proxima questao: {e}", Colors.RED)
            return False
    log("Nao encontrei a seta da proxima questao.", Colors.RED)
    return False


def preencher_campo_por_seletor(page: Page, seletor: str, valor: str) -> bool:
    try:
        loc = page.locator(seletor).first
        if loc.count() == 0:
            return False
        loc.click()
        loc.fill("")
        loc.fill(valor)
        return True
    except Exception:
        return False


def debug_pagina(page: Page, nome: str = "pagina"):
    if not DEBUG_MODE:
        return
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = f"debug/{nome}_{ts}.html"
        img_path = f"debug/{nome}_{ts}.png"
        
        html = page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        
        page.screenshot(path=img_path, full_page=True)
        
        texto = page.evaluate("() => document.body.innerText") or ""
        texto_path = f"debug/{nome}_{ts}_texto.txt"
        with open(texto_path, "w", encoding="utf-8") as f:
            f.write(texto)
        
        log(f"DEBUG: Salvo {html_path}, {img_path}, {texto_path}", Colors.YELLOW)
        
        inputs = page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll('input, textarea, select'));
            return inputs.map(el => ({
                tag: el.tagName,
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                placeholder: el.placeholder || '',
                value: el.value || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                visible: el.offsetParent !== null
            }));
        }""")
        log(f"DEBUG INPUTS ({nome}): {json.dumps(inputs, ensure_ascii=False, indent=2)}", Colors.CYAN)
        
        botoes = page.evaluate("""() => {
            const botoes = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a[role="button"], [role="button"]'));
            return botoes.map(el => ({
                tag: el.tagName,
                text: (el.innerText || el.textContent || '').trim().substring(0, 100),
                type: el.type || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                visible: el.offsetParent !== null
            }));
        }""")
        log(f"DEBUG BOTOES ({nome}): {json.dumps(botoes, ensure_ascii=False, indent=2)}", Colors.CYAN)
        
    except Exception as e:
        log(f"Erro no debug: {e}", Colors.RED)


def login_plurall(page: Page) -> bool:
    if not PLURALL_EMAIL or not PLURALL_SENHA:
        log("Credenciais do Plurall nao configuradas no .env", Colors.RED)
        return False

    log(f"Abrindo login do Plurall: {PLURALL_LOGIN_URL}", Colors.CYAN)
    try:
        page.goto(PLURALL_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log(f"Erro ao abrir URL do Plurall: {e}", Colors.RED)
        return False

    page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(2)

    if DEBUG_MODE:
        debug_pagina(page, "login_antes")

    # ETAPA 1: usuario / email
    email_loc = None
    email_candidates = [
        "input[data-test-id='input-username']",
        "input[name='username']",
        "input[type='text']",
        "input[type='email']",
        "input[name='email']",
        "input[placeholder*='e-mail']",
        "input[placeholder*='email']",
        "input[placeholder*='usuário']",
        "input[placeholder*='usuario']",
        "input[placeholder*='Login']",
    ]
    for sel in email_candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                email_loc = loc
                break
        except Exception:
            continue

    if not email_loc:
        log("Nao encontrei o campo de usuario/email.", Colors.RED)
        debug_pagina(page, "login_falha_email")
        return False

    try:
        email_loc.click()
        email_loc.fill("")
        email_loc.fill(PLURALL_EMAIL)
        log("Email preenchido.", Colors.GREEN)
    except Exception as e:
        log(f"Erro ao preencher email: {e}", Colors.RED)
        return False

    # Clicar em Continuar
    continuou = False
    continuar_candidates = [
        "button[data-test-id='btn-continue']",
        "button:has-text('Continuar')",
        "button:has-text('Avançar')",
        "button[type='button']",
    ]
    for sel in continuar_candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click()
                log(f"Clicado em Continuar: {sel}", Colors.GREEN)
                continuou = True
                break
        except Exception:
            continue

    if not continuou:
        log("Nao encontrei botao Continuar.", Colors.RED)
        debug_pagina(page, "login_falha_continuar")
        return False

    time.sleep(2)
    page.wait_for_load_state("networkidle", timeout=30000)

    # ETAPA 2: senha
    senha_loc = None
    senha_candidates = [
        "input[data-test-id='input-password']",
        "input[type='password']",
        "input[name='password']",
        "input[name='senha']",
        "input[id*='senha']",
        "input[id*='password']",
        "input[placeholder*='senha']",
        "input[placeholder*='Senha']",
        "input[autocomplete='current-password']",
    ]
    for sel in senha_candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                senha_loc = loc
                break
        except Exception:
            continue

    if not senha_loc:
        log("Nao encontrei o campo de senha na segunda etapa.", Colors.RED)
        debug_pagina(page, "login_falha_senha")
        return False

    try:
        senha_loc.click()
        senha_loc.fill("")
        senha_loc.fill(PLURALL_SENHA)
        log("Senha preenchida.", Colors.GREEN)
    except Exception as e:
        log(f"Erro ao preencher senha: {e}", Colors.RED)
        return False

    time.sleep(0.5)

    # Clicar em Entrar / Login
    login_clicado = False
    login_candidates = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Entrar')",
        "button:has-text('Acessar')",
        "button:has-text('Login')",
        "button:has-text('Entrar no Plurall')",
        "button:has-text('Entrar na plataforma')",
    ]
    for sel in login_candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click()
                log(f"Botao de login clicado: {sel}", Colors.GREEN)
                login_clicado = True
                break
        except Exception:
            continue

    if not login_clicado:
        try:
            page.keyboard.press("Enter")
            log("Tentando login com Enter...", Colors.YELLOW)
            login_clicado = True
        except Exception:
            pass

    if not login_clicado:
        log("Nao consegui clicar em nenhum botao de login.", Colors.RED)
        debug_pagina(page, "login_falha_botao")
        return False

    time.sleep(4)
    page.wait_for_load_state("networkidle", timeout=30000)
    if DEBUG_MODE:
        debug_pagina(page, "login_apos")

    texto_apos = extrair_texto_pagina(page).lower()
    if any(p in texto_apos for p in ["erro", "incorreta", "inválida", "invalida", "tente novamente"]):
        log("Possivel erro de login detectado no texto da pagina.", Colors.RED)
        log("Abrindo modo de login manual. Faca login no navegador aberto.", Colors.YELLOW)
        log("Quando terminar, pressione ENTER aqui...", Colors.YELLOW)
        input()
        time.sleep(2)
        debug_pagina(page, "login_manual_erro")
        return True

    return True


def resolver_questao(page: Page) -> bool:
    log("Lendo conteudo da pagina...", Colors.CYAN)

    if not pagina_de_prova_aberta(page):
        log(
            f"A pagina atual nao e uma prova aberta ({page.url}). "
            "Abra a questao no Plurall e pressione ENTER novamente.",
            Colors.YELLOW,
        )
        return False
    
    # Aguarda o React renderizar o conteúdo
    time.sleep(2)
    carregar_conteudo_completo(page)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    
    texto_pagina = extrair_texto_pagina(page)
    textos_acessiveis = extrair_textos_acessiveis(page)
    if textos_acessiveis:
        texto_pagina = f"{texto_pagina}\n{textos_acessiveis}".strip()
    diagnosticar_frames(page)
    if DEBUG_MODE:
        debug_pagina(page, "questao_lida")
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            with open(f"debug/questao_texto_real_{ts}.txt", "w", encoding="utf-8") as arquivo:
                arquivo.write(texto_pagina)
        except Exception as e:
            log(f"Nao foi possivel salvar o texto real: {e}", Colors.YELLOW)
    if not texto_pagina:
        log("Nenhum texto encontrado na pagina.", Colors.RED)
        if DEBUG_MODE:
            debug_pagina(page, "questao_sem_texto")
        return False
    log(f"Texto real extraido ({len(texto_pagina)} caracteres): {texto_pagina[:1000]}", Colors.CYAN)
    if len(texto_pagina) > 1000:
        log(f"Final do texto real: {texto_pagina[-500:]}", Colors.CYAN)

    elementos = extrair_elementos_clicaveis(page)
    opcoes = filtrar_opcoes_questao(elementos)
    campos = extrair_campos_texto(page)
    log(f"Elementos interativos encontrados: {len(elementos)}", Colors.CYAN)
    log(f"Candidatos enviados como alternativas: {[opcao['texto'] for opcao in opcoes]}", Colors.CYAN)

    if len(opcoes) < 2 and not campos:
        log("A questao ainda nao carregou alternativas ou campo de resposta. "
            "Abra a questao e tente novamente.", Colors.YELLOW)
        return False

    captura = None
    seletores_conteudo = [
        "#container-hold-content",
        "main",
        "[aria-label='Conteudo principal']",
        "[role='main']",
    ]
    for seletor in seletores_conteudo:
        try:
            area = page.locator(seletor).first
            if area.count() > 0 and area.is_visible():
                captura = area.screenshot(
                    animations="disabled",
                    type="jpeg",
                    quality=85,
                )
                log(f"Captura da area da questao preparada para a IA ({seletor}).", Colors.CYAN)
                break
        except Exception:
            continue
    if captura is None:
        try:
            captura = page.screenshot(
                full_page=True,
                animations="disabled",
                type="jpeg",
                quality=75,
            )
            log("Captura completa da pagina preparada para a IA.", Colors.CYAN)
        except Exception as e:
            log(f"Nao foi possivel capturar a pagina: {e}", Colors.YELLOW)

    resposta = chamar_nvidia(texto_pagina, opcoes, captura, "image/jpeg")
    if not resposta:
        log("IA nao retornou resposta.", Colors.RED)
        return False

    log(f"IA sugeriu: {resposta}", Colors.GREEN)

    if clicar_opcao_por_indice(page, opcoes, resposta):
        time.sleep(1)
        if avancar_questao(page):
            return True
    elif not opcoes and digitar_resposta(page, resposta):
        time.sleep(1)
        if avancar_questao(page):
            return True
    elif opcoes:
        log(f"A IA retornou uma resposta invalida para as {len(opcoes)} alternativas: {resposta}", Colors.RED)
    else:
        log("Nenhum campo de resposta disponivel na pagina.", Colors.RED)
    return False


def main():
    log("Iniciando Bot de Quizzes Escolares (NVIDIA + Playwright)", Colors.CYAN)
    with sync_playwright() as p:
        while True:
            browser = None
            try:
                browser = p.chromium.launch(headless=HEADLESS)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    device_scale_factor=2,
                )
                page = context.new_page()

                if not login_plurall(page):
                    log("Falha no login automatico. Feche o navegador e verifique.", Colors.RED)
                    input("Pressione ENTER para tentar novamente...")
                    continue

                log("Login realizado. Va ate a primeira questao.", Colors.YELLOW)
                log("Dica: no Plurall, entre em Maestro / Simulados / Atividades ate abrir a questao.", Colors.YELLOW)
                log("Quando a questao estiver aberta na tela, pressione ENTER aqui...", Colors.YELLOW)
                while True:
                    input()
                    page = localizar_pagina_de_prova(context, page)
                    if pagina_de_prova_aberta(page):
                        break
                    log("A prova ainda nao esta aberta. Navegue ate avaliacao e pressione ENTER novamente.", Colors.YELLOW)

                while True:
                    ok = resolver_questao(page)
                    if not ok:
                        log("Nao foi possivel resolver esta questao. Corrija a tela ou aguarde a API e pressione ENTER para tentar novamente.", Colors.RED)
                        input()
                        if not pagina_de_prova_aberta(page):
                            break
                        continue
                    time.sleep(1.5)
            except KeyboardInterrupt:
                log("\nBot interrompido. Reiniciando; pressione ENTER quando a questao estiver aberta...", Colors.YELLOW)
            finally:
                if browser:
                    browser.close()


if __name__ == "__main__":
    main()
