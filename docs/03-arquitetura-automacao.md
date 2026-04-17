# Fase 3 e 4: arquitetura da automacao

## Objetivo

Montar um pipeline que:

1. recebe um link;
2. baixa e organiza a fonte;
3. transcreve;
4. sugere cortes virais;
5. renderiza em 9:16 com legenda;
6. publica via TikTok Content Posting API.

## Stack escolhida

- Python para orquestracao;
- `yt-dlp` para ingestao por URL;
- `ffmpeg` para extrair audio e renderizar;
- OpenAI Speech-to-Text para transcricao;
- heuristica local para ranquear cortes;
- TikTok Login Kit + Content Posting API para autenticacao e postagem.

## Fases do pipeline

### Fase 1: pesquisa

Entregue em `docs/`.

### Fase 2: ingestao e nichos

Modulo: `pipeline/youtube_ingest.py`

Responsabilidades:

- baixar fonte;
- salvar metadata;
- exigir `rights_status`;
- criar `run_id`.

### Fase 3: edicao

Modulos:

- `pipeline/transcription.py`
- `pipeline/clip_scoring.py`
- `pipeline/subtitles.py`
- `pipeline/rendering.py`

Responsabilidades:

- extrair audio;
- transcrever;
- selecionar janelas candidatas;
- gerar `.ass`;
- renderizar corte final.

### Fase 4: postagem

Modulo: `platforms/tiktok.py`

Responsabilidades:

- montar URL de autorizacao;
- trocar `code` por token;
- consultar `creator_info/query`;
- iniciar `Direct Post`;
- enviar video em chunks;
- consultar status.

### Fase 5: aprendizado estilo reforco

Modulo: `learning/bandit.py`

Responsabilidades:

- escolher o proximo pacote de estrategia;
- balancear exploracao vs exploracao do que ja funciona;
- atualizar recompensa por post;
- decidir quando pivotar de nicho, hook, duracao e slot;
- manter a meta explicita de `10k` seguidores e `100k` views totais.

## Observacoes importantes sobre TikTok API

- `video.publish` e usado para direct post.
- `video.upload` e usado para inbox draft upload.
- clientes nao auditados ficam presos a private/self only.
- o app precisa honrar as opcoes retornadas por `creator_info/query`.
- quando o asset esta no seu servidor, o proprio TikTok recomenda `PULL_FROM_URL`.

## Variaveis de ambiente criticas

### Obrigatorias para transcricao

- `OPENAI_API_KEY`

### Obrigatorias para TikTok

- `TIKTOK_CLIENT_KEY`
- `TIKTOK_CLIENT_SECRET`
- `TIKTOK_REDIRECT_URI`

### Obrigatorias para operacao madura

- `TIKTOK_WEBHOOK_URL`
- `TIKTOK_WEBHOOK_VERIFY_TOKEN`
- `STORAGE_PUBLIC_BASE_URL`
- `STORAGE_UPLOAD_ROOT`

## Roadmap sugerido

### MVP privado

- usar `SELF_ONLY`;
- testar 5 a 10 videos;
- medir qualidade de corte e legenda;
- ajustar hooks.

### MVP semi-manual

- integrar revisao humana antes de postar;
- liberar edit da caption;
- guardar status de cada `publish_id`.

### Versao produto

- fluxo com consentimento explicito;
- preview do post;
- auditoria TikTok;
- `PULL_FROM_URL`;
- webhooks;
- analytics e ranking por performance real.

## Proximo salto tecnico recomendado

Se quiser continuar depois desta base, os proximos upgrades mais valiosos sao:

1. detecao de speaker e rosto para crop mais inteligente;
2. ranking de cortes com LLM alem da heuristica;
3. A/B de hook e caption;
4. webhook receiver para status do TikTok;
5. dashboard de analytics por corte.

