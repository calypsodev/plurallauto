# plurallauto

Um script que automatiza o login na plataforma **Plurall** e utiliza um modelo de visão (via API da NVIDIA) para responder automaticamente às tarefas/atividades da plataforma.

## Como funciona

O bot faz login automático no Plurall usando o **Playwright**, navega até as tarefas/quizzes e usa um modelo de linguagem com visão (`meta/llama-3.2-90b-vision-instruct`, servido pela API da NVIDIA) para interpretar e responder às questões automaticamente.

## Pré-requisitos

- Python 3.9+
- Uma chave de API da [NVIDIA](https://integrate.api.nvidia.com/)
- Conta ativa no Plurall

## Instalação

```bash
git clone https://github.com/calypsodev/plurallauto.git
cd plurallauto
pip install -r requirements.txt
playwright install
```

## Configuração

1. Copie o arquivo de exemplo de variáveis de ambiente:

```bash
cp .env.example .env
```

2. Edite o `.env` com suas informações:

| Variável | Descrição | Padrão |
|---|---|---|
| `NVIDIA_API_KEY` | Sua chave de API da NVIDIA | — |
| `NVIDIA_API_URL` | Endpoint da API da NVIDIA | `https://integrate.api.nvidia.com/v1/chat/completions` |
| `NVIDIA_MODEL` | Modelo usado para interpretar as questões | `meta/llama-3.2-90b-vision-instruct` |
| `NVIDIA_API_TIMEOUT` | Timeout (em segundos) para chamadas à API | `120` |
| `NVIDIA_VERIFY_SSL` | Verificar certificado SSL nas chamadas à API | `true` |
| `CLICAR_VISUALIZAR` | Clicar automaticamente para visualizar as questões | `true` |
| `HEADLESS` | Rodar o navegador em modo headless (sem interface) | `false` |
| `PLURALL_LOGIN_URL` | URL de login do Plurall | `https://login.plurall.net/` |
| `PLURALL_EMAIL` | Seu e-mail de login no Plurall | — |
| `PLURALL_SENHA` | Sua senha de login no Plurall | — |

> ⚠️ Nunca faça commit do arquivo `.env` com suas credenciais reais — ele já está listado no `.gitignore`.

## Uso

```bash
python bot_quiz.py
```

Os logs de execução são exibidos no terminal com cores para facilitar o acompanhamento, e capturas de tela (quando aplicável) são salvas na pasta `debug/`.

## Aviso

Este projeto automatiza a resolução de atividades acadêmicas. O uso é de responsabilidade do usuário — verifique se está de acordo com as regras da sua instituição de ensino antes de utilizar.

## Licença

Defina a licença do projeto aqui (ex.: MIT).
