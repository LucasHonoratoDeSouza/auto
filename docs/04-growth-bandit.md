# Fase 5: growth engine estilo reforco

## Objetivo

O projeto agora nao para em postar. Ele passa a ter um **controlador de crescimento**.

Meta declarada:

- `10.000` seguidores
- `100.000` views totais no perfil

## Modelo mental

Nao estamos montando RL academico completo com ambiente simulavel. O melhor fit aqui e um **multi-armed bandit com reward continuo**, porque:

- cada post e um experimento;
- a recompensa chega rapido;
- voce precisa decidir a proxima estrategia antes de ter muita amostra;
- o problema real e exploracao vs exploit, nao credit assignment longo.

## O que um "arm" representa

Cada arm e um pacote de decisao editorial:

- nicho
- estilo de hook
- faixa de duracao
- horario
- estilo de caption
- intensidade visual da legenda

Exemplo:

- `business-question-short-lunch`
- `psychology-contrarian-medium-night`
- `ai-tech-story-short-morning`

## Funcao de recompensa

O reward do post foi desenhado para a meta de seguidores e views, nao para vaidade.

Pesos base:

- `40%` follows gained
- `25%` views nas primeiras 24h
- `15%` completion rate
- `10%` shares
- `10%` profile visits

Ajustes:

- bonus quando um post passa da linha de corte de breakout;
- penalidade forte se o post ficar inelegivel para For You;
- penalidade leve se o post morrer cedo.

## Regras de pivot

### Pivot de subnicho

Se a media de reward da janela recente ficar abaixo do minimo por varios posts, o sistema sinaliza pivot.

### Pivot de formato

Se views sobem mas follows nao acompanham:

- manter o tema;
- mudar hook;
- mudar caption;
- aproximar CTA de perfil/serie;
- testar duracao mais curta.

### Pivot total

Se 2 ou mais nichos tiverem volume suficiente e ainda assim reward fraco:

- mudar cluster de assunto;
- manter apenas o que for reaproveitavel do pacote visual.

## Protocolo de refresh para nao ficar datado

Toda semana:

1. revisar `Creator Search Insights` e salvar topicos com `content gap`;
2. revisar `Comment Insights` para ver perguntas recorrentes e sentimentos;
3. revisar 20 a 30 posts do proprio feed `For You` no subnicho;
4. anotar:
- hooks repetidos demais;
- sons/movimentos/text overlays que estao vivos;
- formatos saturados que ja parecem template;
5. atualizar os proximos arms com o que esta vivo agora.

## Regras anti-automacao

O sistema deve maximizar performance, mas sem parecer bot de conteudo.

Sinais que precisamos evitar:

- mesmo hook visual em todos os posts;
- legenda sempre em caps lock e no mesmo ritmo;
- hashtags genericas demais;
- todos os cortes com o mesmo framing;
- CTA identica em serie longa;
- publicacoes parecendo export cru de YouTube.

O growth engine deve preferir arms que soem:

- nativos;
- contextuais;
- editados para TikTok;
- ligados a busca, comentario e cultura atual da plataforma.

## Quando usar Promote

Promote existe e e oficial, mas eu trataria como acelerador, nao muleta.

Regra:

- primeiro validar organicamente quais posts convertem em perfil e follow;
- depois, se fizer sentido, promover vencedores publicos usando som original ou som com uso comercial permitido.

Promote nao substitui criativo nativo.

## Estrategia operacional recomendada

### Estagio 1: exploracao brutal

Primeiros `12` a `20` posts:

- testar 4 nichos;
- 3 estilos de hook;
- 2 faixas de duracao;
- 3 slots de postagem.

Meta:

- descobrir quais combinacoes geram distribuicao inicial e ganho de seguidor, nao so views.

### Estagio 2: exploracao guiada

Depois de algum sinal:

- cortar os piores nichos;
- dobrar em 2 ou 3 arms promissores;
- testar variacoes finas de caption, CTA e framing.

### Estagio 3: exploit

Quando um arm passar a gerar reward alto com consistencia:

- aumentar frequencia;
- criar serie;
- abrir subserie derivada;
- reciclar padrao visual e horario vencedor.

## O que eu faria como diretor da operacao

1. Comecaria com `business`, `psychology`, `money` e `ai_tech`.
2. Usaria hooks `question`, `contrarian` e `story`.
3. Separaria duracao em:
- `short`: 18-25s
- `medium`: 26-35s
4. Testaria slots:
- `morning`
- `lunch`
- `night`
5. Cortaria qualquer nicho com amostra minima e reward estruturalmente fraco.
6. Se um nicho der view mas nao der follow, eu nao descarto de cara:
- eu troco CTA, framing e serializacao antes de matar.

## Regra pratica para bater 10k seguidores

Nao basta video viral isolado. O sistema precisa maximizar:

- retorno por view em follow;
- consistencia de tema;
- repeticao de formato vencedor;
- empilhamento de series.

Traduzindo:

- o melhor post nao e o mais visto;
- e o que mais empurra o perfil para as duas metas ao mesmo tempo.

## Comando operacional

1. `strategy-init`
2. `strategy-next`
3. produzir/postar com o arm sugerido
4. `strategy-feedback`
5. repetir

## Limites que nao devem ser quebrados

Mesmo com objetivo agressivo, o sistema nao deve:

- violar direitos autorais;
- mascarar conteudo de terceiros como original;
- produzir spam;
- burlar elegibilidade do For You;
- quebrar os requisitos de auditoria da API do TikTok.
