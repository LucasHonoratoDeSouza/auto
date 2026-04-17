# TikTok Automation

Pipeline inicial para:

1. pesquisar o que hoje realmente influencia distribuicao no TikTok;
2. receber um link de video, baixar a fonte e preparar um run de trabalho;
3. transcrever, ranquear cortes curtos e renderizar videos verticais com legenda burn-in;
4. operar em fila semi-automatica, exportando a fila para o GitHub e enviando o video por email via GitHub Actions antes da janela de postagem ou, quando liberado, postar via TikTok API.
5. aprender com performance via loop estilo reforco/bandit para decidir o proximo experimento.
6. operar por interface web local para colar um link e gerar cortes sem usar o CLI no dia a dia.

## Aviso importante

Este projeto foi montado com um trilho de compliance porque a propria documentacao oficial do TikTok diz que:

- clientes nao auditados so postam em `SELF_ONLY` / privado;
- apps que copiam conteudo arbitrario de outras plataformas nao sao aceitaveis para auditoria;
- o usuario precisa ter controle e consentimento explicito antes do envio;
- nao e recomendado adicionar watermark ou branding promocional no video enviado.

Se voce quiser operar com o nicho de cortes, a rota mais segura e:

- usar videos seus;
- usar videos com licenca/permissao formal;
- ou construir um fluxo onde o dono do conteudo autoriza e revisa a postagem.

## Estrutura

- `docs/01-pesquisa-algoritmo-tiktok.md`: pesquisa oficial e implicacoes para alcance.
- `docs/02-nicho-cortes.md`: estrategia do nicho de cortes e scorecard de selecao.
- `docs/03-arquitetura-automacao.md`: arquitetura por fases e operacao.
- `docs/04-growth-bandit.md`: sistema de aprendizado, reward e regras de pivot.
- `src/tiktok_automation/`: CLI e modulos do pipeline.

## Setup

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
cp .env.example .env
```

Preencha ao menos:

- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` e `TIKTOK_REDIRECT_URI` para o fluxo de Login Kit.
- `SMTP_HOST`, `SMTP_PORT`, `NOTIFICATION_EMAIL_TO` e `NOTIFICATION_EMAIL_FROM` para o modo semi-automatico por email via GitHub Actions.

Para comecar sem pagar:

- deixe `TRANSCRIPTION_PROVIDER=auto`;
- o pipeline tentara `YouTube captions -> faster-whisper local`;
- `OPENAI_API_KEY` e totalmente opcional.

## Interface web

Subir a interface local:

```bash
uv run tiktok-automation web --host 127.0.0.1 --port 8787
```

Depois abra:

```text
http://127.0.0.1:8787
```

Fluxo:

1. colar o link do YouTube;
2. clicar em `Gerar cortes`;
3. esperar as etapas `download -> transcript -> ranking -> render`;
4. revisar os videos prontos, ajustar a caption e clicar em `Aprovar`;
5. o video entra na fila, o sistema escolhe a proxima janela automaticamente e sincroniza o pacote para o GitHub;
6. 5 minutos antes da janela, o GitHub Actions envia email com o video, caption e hashtags;
7. depois do upload manual no TikTok, clique em `Marcar postado`.

Os jobs ficam em `workspace/web_jobs/` e os runs completos continuam em `workspace/runs/<run_id>/`.
A fila de postagem fica em `workspace/post_queue.json`.
A fila publicada para o GitHub fica em `github_queue/`.

Variaveis novas para o modo semi-automatico:

- `QUEUE_EXECUTION_MODE=github_actions_email`
- `NOTIFICATION_LEAD_MINUTES=5`
- `NOTIFICATION_EMAIL_TO=voce@dominio.com`
- `NOTIFICATION_EMAIL_FROM=voce@dominio.com`
- `GITHUB_QUEUE_AUTOPUSH=true`
- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USERNAME=voce@dominio.com`
- `SMTP_PASSWORD=sua_senha_de_app`

Se quiser incluir um link clicavel junto no email, configure tambem:

- `APP_PUBLIC_BASE_URL=https://seu-host-publico`

Para o GitHub Actions funcionar com o app fechado, configure os secrets do repo:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_SSL`
- `SMTP_USE_TLS`
- `MAIL_TO`
- `MAIL_FROM`
- `MAIL_SENDER_NAME`
- `NOTIFICATION_LEAD_MINUTES`
- `NOTIFICATION_ATTACH_VIDEO_MAX_MB`

## Uso rapido

Baixar um video, transcrever, ranquear cortes e renderizar os melhores:

```bash
uv run tiktok-automation from-link \
  --url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --rights-status permissioned \
  --top-k 5 \
  --render-top-k 3
```

Se quiser forcar apenas caminho gratis:

```bash
TRANSCRIPTION_PROVIDER=local uv run tiktok-automation from-link \
  --url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --rights-status permissioned
```

Gerar a URL de autorizacao do TikTok:

```bash
uv run tiktok-automation tiktok-auth-url
```

Trocar o `code` do callback por token:

```bash
uv run tiktok-automation tiktok-exchange-code --code "CODE_RECEBIDO"
```

Postar um video renderizado:

```bash
uv run tiktok-automation tiktok-post \
  --video output/<run_id>/01-meu-corte.mp4 \
  --title "Hook curto e claro"
```

## Saidas do pipeline

Cada execucao cria um run em `workspace/runs/<run_id>/` com:

- `metadata.json`
- `transcript.json`
- `candidates.json`
- `rendered.json`

Os videos finais vao para `output/<run_id>/`.

## Loop de aprendizado

Inicializar o estado do projeto:

```bash
uv run tiktok-automation strategy-init
```

Pedir as proximas estrategias sugeridas:

```bash
uv run tiktok-automation strategy-next
```

Atualizar o sistema depois de um post:

```bash
uv run tiktok-automation strategy-feedback \
  --arm-id business-question-short-lunch \
  --views-24h 8200 \
  --views-2h 1900 \
  --shares 34 \
  --profile-visits 87 \
  --follows-gained 29 \
  --completion-rate 0.41
```

## Refresh continuo

O playbook nao deve ficar congelado. A rotina minima de refresh e:

- checar `Creator Search Insights` para topics com `content gap`;
- usar `Comment Insights` para transformar perguntas reais em novos videos;
- revisar o proprio `For You` feed e Creative Center para detectar sinais e momentos;
- trocar criativos antes de fadiga, sem perder identidade editorial;
- evitar visual que fique "template demais" por muitos posts seguidos.

## Custo zero no comeco

O caminho padrao agora e:

1. usar captions/transcript do YouTube quando existirem;
2. se nao existir, usar `faster-whisper` local;
3. so usar OpenAI se voce ligar isso explicitamente.

Na pratica, isso permite operar sem credito algum da OpenAI.
