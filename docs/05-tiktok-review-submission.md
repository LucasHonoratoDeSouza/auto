# TikTok Review Submission

Baseado na documentacao oficial consultada em **April 17, 2026**.

## Posicionamento correto

Nao submeta o app como ferramenta interna, pessoal, ou para repostar conteudo arbitrario de terceiros. O melhor enquadramento verdadeiro para este projeto e:

- workflow invite-only para creators e parceiros aprovados;
- uso em conteudo proprio, licenciado, ou permissionado;
- review humano antes do upload;
- captions e hashtags editaveis antes do envio;
- onboarding manual por formulario publico.

## Nome do app

Use um nome que bata com o site e nao mencione TikTok.

Sugestao:

- `Linvesther Studio`

## Descricao curta

Use algo assim no campo publico:

`Invite-only workflow for creators and approved partners to clip long videos, review metadata, and queue short-form posts.`

## Categoria

Se o portal oferecer algo proximo, prefira:

- `Productivity`
- ou `Media & Entertainment`

## URLs para o app review

Substitua pela URL publica final do site:

- Homepage: `https://SEU-SITE`
- Privacy Policy: `https://SEU-SITE/privacy`
- Terms of Service: `https://SEU-SITE/terms`
- Access request form: `https://SEU-SITE/#request-access`

## Texto para explicar produtos e scopes

### Se estiver usando `user.info.basic` + `video.upload`

```text
Linvesther Studio is an invite-only workflow for creators and approved partners who manage owned, licensed, or permissioned media. Users import long-form source material, review short-form clips, edit captions and hashtags, and explicitly approve exports before anything is sent to TikTok. We use user.info.basic to identify the connected TikTok account and show the creator which account is being used during the export flow. We use video.upload to send approved media to TikTok only after user review and consent, so the creator can continue the final editing and publishing flow inside TikTok.
```

### Se depois liberar `video.publish`

```text
Linvesther Studio is an invite-only workflow for creators and approved partners who manage owned, licensed, or permissioned media. Users import long-form source material, review short-form clips, edit captions and hashtags, and explicitly approve exports before anything is sent to TikTok. We use user.info.basic to identify the connected TikTok account and show the creator which account is being used during the export flow. We use video.publish only after the user has reviewed the selected clip, edited metadata if needed, and consented to publish to their own authorized TikTok account.
```

## O que mostrar no demo video

O video de review precisa mostrar o fluxo completo em sandbox ou production review:

1. abrir o site publico;
2. mostrar a homepage, privacy policy e terms;
3. abrir o formulario de request access;
4. abrir a interface do produto;
5. conectar a conta TikTok com Login Kit;
6. mostrar a conta conectada no fluxo de export;
7. mostrar o clip selecionado;
8. mostrar caption e hashtags editaveis;
9. mostrar que o envio so comeca depois da aprovacao do usuario;
10. mostrar o status do envio ou da fila depois do upload.

## O que falar se pedirem publico-alvo

Use uma resposta verdadeira e defensavel:

```text
The product is currently in invite-only beta, but access is requested through a public onboarding form. We are onboarding creators and approved media partners who publish owned, licensed, or permissioned source material and need a controlled workflow for short-form publishing.
```

## O que mandar no formulario de access request

Esses campos ja estao no site e ajudam a sustentar o app review:

- full name
- email
- TikTok handle
- primary channel URL
- company or brand
- rights model
- estimated posts per week
- team size
- use case description
- rights confirmation checkbox

## Checklist antes de submeter

- o site publico abre sem login;
- `Privacy Policy` e `Terms of Service` estao visiveis;
- o nome do app bate com o site;
- o app icon esta pronto em `PNG 1024x1024`;
- o fluxo mostra caption/hashtags editaveis;
- o fluxo mostra aprovacao explicita antes do upload;
- o fluxo nao promete repost de conteudo arbitrario;
- o demo video mostra o export de ponta a ponta.

## Fontes oficiais

- https://developers.tiktok.com/doc/app-review-guidelines/
- https://developers.tiktok.com/doc/content-sharing-guidelines/
- https://developers.tiktok.com/doc/content-posting-api-get-started//
- https://developers.tiktok.com/doc/content-posting-api-reference-upload-video
- https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
