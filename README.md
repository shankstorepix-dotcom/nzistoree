# NziStore

Loja de alta performance e segurança com arquitetura **Backend-First / Zero-Trust no Cliente**, catálogo com variantes, checkout integrado com Pix, entrega automática/manual, painel `/dashboard` administrativo e banco de dados PostgreSQL (Supabase) blindado com Row Level Security (RLS) Deny-by-Default.

---

# 📖 GUIA PASSO A PASSO: DO ZERO AO DEPLOY NA VERCEL E SUPABASE

Siga este passo a passo à risca para colocar sua loja em produção com 100% de segurança e sem erros.

---

## 🛠️ ETAPA 1: Gerar as Chaves Criptográficas Seguras

No terminal da sua máquina (onde está o projeto), execute os dois comandos abaixo para gerar chaves criptográficas fortes de 256 bits:

```bash
# 1. Gerar DATABASE_KEY (chave de 64 caracteres hexadecimais para criptografia AES-256-GCM):
python3 -c "import secrets; print(secrets.token_hex(32))"

# 2. Gerar SECRET_KEY (chave para sessões e tokens CSRF):
python3 -c "import secrets; print(secrets.token_hex(32))"
```

> 📌 **Guarde esses dois valores gerados em um bloco de notas temporário.** Você vai usá-los no `.env` e nas variáveis de ambiente da Vercel.

---

## 🗄️ ETAPA 2: Configurar o Supabase (Banco de Dados com RLS)

O Supabase será o banco de dados oficial do seu backend na nuvem.

### 2.1 Criar o Projeto
1. Acesse **[supabase.com](https://supabase.com)** e crie uma conta ou faça login.
2. No painel principal, clique no botão verde **"New Project"**.
3. Preencha as informações:
   - **Organization**: Escolha a sua organização padrão.
   - **Name**: `nzistore` (ou o nome que preferir).
   - **Database Password**: Escolha uma senha forte (anote essa senha no seu bloco de notas).
   - **Region**: Escolha `São Paulo (sa-east-1)` (ou a região mais próxima dos seus clientes).
4. Clique em **"Create new project"** e aguarde 1 a 2 minutos até o status ficar verde.

### 2.2 Rodar o Script de Tabelas e RLS Deny-by-Default
1. No menu lateral esquerdo do Supabase, clique no ícone **SQL Editor** (`>_`).
2. Clique no botão **"New query"**.
3. Abra o arquivo [`supabase/schema.sql`](file:///home/ph/Área de trabalho/NziStore/supabase/schema.sql) deste projeto.
4. Copie **TODO o conteúdo** do arquivo `supabase/schema.sql` e cole dentro do editor SQL do Supabase.
5. Clique no botão verde **"Run"** (no canto inferior direito do editor) ou pressione `Ctrl + Enter`.
6. Aguarde a mensagem: `Success. No rows returned`.
> 🔒 **Por que isso é seguro?** Todas as 27 tabelas foram criadas com `ROW LEVEL SECURITY` ativado e permissões revogadas de `anon` e `PUBLIC`. Ninguém consegue acessar ou roubar dados diretamente pela web; apenas o backend autenticado tem permissão.

### 2.3 Copiar a Connection String (`SUPABASE_DB_URL`)
1. No menu lateral esquerdo, clique no ícone de engrenagem **Project Settings**.
2. Clique na aba **Database**.
3. Role a página até a seção **Connection string** e clique na aba **URI**.
4. Copie o endereço completo exibido (formato: `postgresql://postgres:[YOUR-PASSWORD]@db.[REF].supabase.co:5432/postgres` ou com modo pooler).
5. Substitua `[YOUR-PASSWORD]` pela senha que você escolheu no passo 2.1.
6. Guarde essa URL completa no seu bloco de notas: ela é sua variável `SUPABASE_DB_URL`.

---

## 💻 ETAPA 3: Preparar o Git e Enviar para o GitHub

Agora vamos subir o código da sua loja para o GitHub com total proteção (arquivos com senhas e segredos já estão no `.gitignore` e não serão enviados).

### 3.1 Instalar o Git (se ainda não tiver)
No terminal Linux:
```bash
sudo apt update && sudo apt install -y git
```

### 3.2 Criar o Repositório no GitHub
1. Acesse **[github.com/new](https://github.com/new)**.
2. Em **Repository name**, coloque: `nzistore`.
3. Escolha **Private** (obrigatório para manter o código do seu negócio seguro).
4. **IMPORTANTE**: Deixe as caixas *Add a README file*, *Add .gitignore* e *Choose a license* **DESMARCADAS** (o projeto já tem todos esses arquivos).
5. Clique no botão verde **"Create repository"**.

### 3.3 Inicializar e Enviar o Código
No terminal, dentro da pasta da loja (`/home/ph/Área de trabalho/NziStore`), execute os comandos abaixo em ordem (substitua `SEU-USUARIO` pelo seu usuário do GitHub):

```bash
# 1. Iniciar o repositório git local:
git init

# 2. Adicionar todos os arquivos do projeto:
git add .

# 3. Criar o primeiro commit:
git commit -m "feat: loja nzistore zero-trust production-ready"

# 4. Definir a branch principal como main:
git branch -M main

# 5. Conectar com o seu repositório do GitHub (troque pelo seu link):
git remote add origin https://github.com/SEU-USUARIO/nzistore.git

# 6. Enviar para o GitHub:
git push -u origin main
```

*(Se o GitHub solicitar login, informe seu usuário e seu Personal Access Token gerado nas configurações do GitHub).*

---

## ⚡ ETAPA 4: Fazer o Import e Deploy na Vercel

A Vercel hospedará o backend Python Serverless e servirá sua loja com velocidade global.

### 4.1 Importar o Projeto
1. Acesse **[vercel.com](https://vercel.com)** e faça login com sua conta GitHub.
2. No seu dashboard, clique no botão **"Add New..."** e selecione **"Project"**.
3. Em **Import Git Repository**, procure o repositório `nzistore` e clique no botão **"Import"**.

### 4.2 Configurar o Projeto na Vercel
1. Em **Project Name**, deixe `nzistore`.
2. Em **Framework Preset**, deixe selecionado **Other**.
3. Em **Root Directory**, deixe `./`.
4. Não altere as opções de Build and Output Settings (o arquivo [`vercel.json`](file:///home/ph/Área de trabalho/NziStore/vercel.json) e [`api/index.py`](file:///home/ph/Área de trabalho/NziStore/api/index.py) já controlam isso automaticamente).

### 4.3 Cadastrar as Variáveis de Ambiente (Environment Variables)
Antes de clicar em Deploy, abra a seção **Environment Variables** e cadastre as seguintes variáveis (uma por uma):

| Nome da Variável | Valor a Preencher |
| :--- | :--- |
| `APP_ENV` | `production` |
| `PUBLIC_ORIGIN` | `https://nzistore.vercel.app` *(ou seu domínio definitivo)* |
| `DATABASE_KEY` | *(A chave de 64 caracteres hex que você gerou na Etapa 1)* |
| `SECRET_KEY` | *(A chave de 64 caracteres hex que você gerou na Etapa 1)* |
| `SUPABASE_DB_URL` | *(A Connection String URI do Supabase da Etapa 2.3)* |
| `PAYMENT_PROVIDER` | `pantera` *(ou `mistic`)* |
| `PANTERA_API_KEY` | *(Sua chave de API do provedor de Pix)* |
| `DISCORD_WEBHOOK_URL` | *(URL do webhook do canal privado do Discord para avisos de compra)* |

> 💡 **Nota sobre E-mail (SMTP)**: Para envio automático de códigos OTP de 6 dígitos no cadastro e recuperação de senha, adicione também: `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD` e `SMTP_FROM`. Se ainda não tiver um provedor SMTP (como Resend ou SendGrid), a loja funciona normalmente e permite cadastro direto.

### 4.4 Clicar em Deploy
1. Clique no botão azul **"Deploy"**.
2. Aguarde cerca de 1 a 2 minutos enquanto a Vercel compila o ambiente Python.
3. Quando a tela exibir **"Congratulations!"**, sua loja estará no ar!

---

## 🌐 ETAPA 5: Domínio Personalizado e Ajuste Final de Segurança

1. No painel do seu projeto na Vercel, vá em **Settings > Domains**.
2. Adicione o seu domínio próprio (ex: `nzistore.com.br` ou `loja.seusite.com`).
3. Siga as instruções da Vercel para apontar os registros DNS (CNAME ou A) no seu provedor de domínio (Registro.br, Cloudflare, etc.).
4. **IMPORTANTE**: Após o domínio estar funcionando, volte em **Settings > Environment Variables**, edite a variável `PUBLIC_ORIGIN` para o seu novo domínio com `https://` (ex: `https://nzistore.com.br`) e clique em **Redeploy** na aba Deployments.
> 🛡️ Isso garante que as proteções contra CSRF e CORS validem estritamente o seu domínio oficial.

---

# 💻 Detalhes Técnicos e Execução Local

## Executar localmente

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app server create-admin
./iniciar-loja.sh
```

Se faltar `venv`, instale o pacote `python3-venv` do sistema. Usuário, senha e PIN de seis dígitos são solicitados interativamente; senha e PIN não aparecem na tela. Use http://localhost:8000 (origem padrão), `/admin` para administração e `/conta` para cadastro/login de clientes. Configure `PUBLIC_ORIGIN` se usar outro endereço/porta. Não há configuração inicial de administrador pela web. O mesmo comando local redefine usuário, senha e PIN administrativos e revoga suas sessões.

## Dados e migração

- `data/secure.db`: banco inteiro criptografado com SQLCipher; inclui clientes, hashes de senha, sessões, catálogo e auditoria.
- Desenvolvimento: chave aleatória em `data/.database-key`, com permissão 0600. Produção: `DATABASE_KEY`, 64 caracteres hexadecimais, fornecida por ambiente/gerenciador de segredos separado do banco. Perder a chave impede recuperar os dados. Guardar chave e banco juntos não protege contra comprometimento do servidor.
- A primeira inicialização importa catálogo e hash do administrador de `data/store.db`, uma única vez, em transação. O administrador migrado precisa executar `create-admin` para configurar o PIN antes de acessar o painel. **O arquivo legado não é apagado nem criptografado automaticamente:** é uma cópia anterior em texto claro (incluindo hash da senha administrativa). Após validar a migração, arquive-o em armazenamento criptografado e retire-o do servidor. Nenhum cliente novo é gravado nele.
- Faça backup consistente do banco com o serviço parado, junto de `uploads/`. Guarde a chave separadamente e teste restaurações. Não copie o banco durante uma escrita. Imagens do catálogo são públicas.
- As senhas e os PINs administrativos têm hash scrypt com salts independentes; não são reversivelmente criptografadas. O cadastro exige confirmação de e-mail via OTP de 6 dígitos (CSPRNG, HMAC-SHA256, expiração de 10 minutos, uso único, limite de 5 tentativas e cooldown de 60 segundos, sem enumeração de contas). Tokens de sessão (`session` de curta duração — 15 minutos — e `refresh` rotacionado) são enviados exclusivamente por cookies `HttpOnly`, `SameSite=Strict` e `Secure` em produção; apenas seu SHA-256 fica no banco. Cada conta permite somente uma sessão ativa por vez (novo login revoga a sessão anterior no servidor). A reutilização de um refresh token já rotacionado revoga imediatamente toda a sessão da conta. A sessão possui expiração absoluta em 8 horas; sair a revoga; mudar a senha revoga todas as sessões da conta.
- Não há token de autenticação ou perfil em localStorage. O carrinho existente contém apenas informações públicas de produtos. `/api/auth/me` retorna somente estado autenticado e token CSRF. O token CSRF não autentica sozinho.

## Proteções e limites reais

Autorização administrativa em cada escrita, consultas parametrizadas, limite de corpo, validação de campos, bloqueio de origem e CSRF, headers de segurança/CSP, arquivos públicos explicitamente permitidos, imagens decodificadas e regravadas sem metadados, registros administrativos de auditoria sem senhas/tokens e limites compartilhados entre workers no banco. Cookies roubados ainda podem ser reutilizados até expirar/revogar: HttpOnly não torna cookies invisíveis ao dono do navegador, Burp ou Caido. HTTPS protege o tráfego em trânsito, não um dispositivo comprometido.

Os limites da aplicação ajudam contra abuso moderado; **não são proteção suficiente contra botnet/DDoS volumétrico**. SQLite/SQLCipher e os limites no banco são uma base para loja pequena, não para alta carga. Um atacante distribuído ainda pode saturar conexões, CPU, banco ou rede. Os buckets expiram, mas ataques massivos exigem bloqueio na borda antes da aplicação.

Anti-deface é redução de risco, não garantia: código e arquivos estáticos devem pertencer ao usuário de implantação e ficar somente leitura para o processo web. Apenas `data/` e `uploads/` precisam ser graváveis. A conta administrativa comprometida ainda permite alterar catálogo. Próximos incrementos recomendados: MFA/passkeys para administradores, confirmação e recuperação de e-mail, monitoramento externo de integridade/disponibilidade, backups fora do servidor, retenção da auditoria e atualizações periódicas de dependências.

## Publicação

1. Instale em `/opt/nzistore`, crie usuário de serviço `nzistore` sem privilégios e conceda escrita somente em `data/` e `uploads/`. Mantenha código, `.venv` e estáticos controlados pelo usuário de implantação/root.
2. Configure `/etc/nzistore.env` (permissão 0600, root) conforme `.env.example`. Para um banco já criado, preserve a chave existente. A aplicação carrega `.env` da raiz automaticamente; variáveis do ambiente têm prioridade. Reinicie servidor e worker após editar.
3. Adapte `deploy/nzistore.service`: Gunicorn limitado, bind apenas em loopback e sandbox systemd com sistema de arquivos somente leitura. O launcher local também usa Gunicorn. `python server.py` é apenas desenvolvimento.
4. Adapte `deploy/nginx.conf`: exemplo de proxy HTTP **interno** com limites de conexão, requisição, corpo e timeouts. Use HTTPS no proxy público ou Cloudflare Tunnel; não exponha esse listener HTTP na Internet. O exemplo não instala nem ativa serviços automaticamente.
5. No Cloudflare, ative proxy/WAF, regras de limite para login/cadastro e proteção de bots conforme o plano; proteja `/admin` e endpoints administrativos com Access quando possível. Bloqueie acesso direto à origem, preferencialmente usando Tunnel. Não faça cache de `/api/*`.
6. O app deliberadamente ignora `X-Forwarded-For` e `CF-Connecting-IP`. Atrás do proxy, os limites por IP da aplicação passam a ser compartilhados pelo IP do proxy. Configure limites por visitante na borda. Não habilite confiança indiscriminada em headers: isso permitiria falsificar IP e contornar limites.
7. Teste HTTPS, cookies Secure, host/origem configurados, permissões, restauração de backup e capacidade sob carga antes de publicar. Os exemplos de Nginx/systemd ainda precisam de validação na hospedagem real.

## Testes

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Testes isolados não alteram o banco da loja. Cobrem autenticação, permissões, CSRF, arquivos privados/HEAD, hash de tokens, expiração/revogação, limite de login, uploads, banco criptografado, configuração de produção e migração repetida sem duplicação.

## Personalizar

Links públicos de contato: `CONFIG` em `static/store.js`. Categorias: mantenha `server.py`, `static/store.js` e formulário administrativo sincronizados. Estilo em `static/style.css` e `static/store.css`; fontes externas Google Fonts permitidas na CSP. Nunca coloque credenciais nesses arquivos.

Referência de segurança do framework: https://flask.palletsprojects.com/en/stable/web-security/

## Pedidos, chat, entrega e Mistic Pay

O checkout agora exige conta na NziStore, cria um pedido persistente e abre `/pedidos#ID`. O cliente gera o Pix, acompanha o status, conversa no chat e baixa os arquivos entregues. No painel, use **Pedidos e suporte** para ver todos os pedidos e responder. Cada cliente acessa somente seus próprios pedidos; IDs aleatórios não substituem a verificação de dono no servidor. O chat consulta novas mensagens a cada 5 segundos enquanto a página está visível.

### Configurar os produtos

No formulário administrativo, escolha **Manual** ou **Automática** e salve. Para automática, cadastre cada unidade de texto em **Estoque para entrega automática**. Cada cadastro gera um arquivo `.txt` para uma unidade comprada, e não pode ser reutilizado em outra compra. O texto pode ter várias linhas e até 20.000 caracteres. Conteúdos idênticos para o mesmo produto são rejeitados, inclusive se já foram vendidos.

A entrega usa uma transação exclusiva no banco: duas confirmações simultâneas não recebem a mesma unidade. Compras com várias unidades recebem os textos agrupados em um `.txt` por item. Se o estoque acabar entre a criação do pedido e o pagamento, o pedido pago fica aguardando estoque; a reposição atende automaticamente os pedidos pendentes por ordem de criação. **Não há reserva de estoque durante o Pix pendente.** O preço, nome, quantidade, modo de entrega e quantidade de Robux são copiados para o pedido; edições posteriores do catálogo não alteram uma compra existente.

Para manual, abra o pedido pago, preencha o texto da entrega e confirme **Entregar arquivo .txt**. Não é possível liberar itens sem pagamento confirmado pela Mistic Pay. Os arquivos são gerados em memória a partir do banco criptografado, com autenticação e `Cache-Control: no-store`; não são publicados em `uploads/`. Produtos que já possuem estoque ou pedidos não podem ser excluídos.

Para Robux, configure a quantidade por unidade no produto. O checkout exige um comprovante assinado da consulta ao Roblox, válido por 15 minutos, e confirmação do destinatário. `robux_quantity` na notificação é a quantidade do pacote multiplicada pelas unidades compradas. A integração **não transfere Robux na plataforma Roblox**: a entrega automática aqui é de texto; o suporte faz a transferência e registra a entrega manualmente quando necessário.

### Credenciais e pagamento

Configure no ambiente dos dois processos (web e worker):

```dotenv
PUBLIC_ORIGIN=https://seu-dominio.com
MISTIC_CLIENT_ID=pk_...
MISTIC_CLIENT_SECRET=sk_...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/ID/TOKEN
```

Use chaves Mistic Pay com apenas `TRANSACTION_CREATE` e `TRANSACTION_READ`. A integração usa Basic Auth da API atual, não as credenciais legadas `ci/cs`. O formulário solicita nome e e-mail, sem CPF; o e-mail é enviado na descrição da cobrança. A documentação atual da Mistic exige `payerDocument`: o envio sem esse campo foi solicitado pelo lojista e pode ser recusado. A compatibilidade real depende de confirmação da Mistic; os testes locais simulam o gateway. Uma recusa é mostrada ao cliente e mantém o pedido em revisão, sem inventar documentos nem gerar QR codes falsos. Valores do pedido são calculados pelo servidor em centavos; são enviados à Mistic em reais. O código Pix copia e cola fica disponível somente ao dono do pedido e ao administrador.

A URL de callback é enviada automaticamente em `projectWebhook`. É uma URL HTTPS com token por pedido; não a publique em logs de acesso. O callback só agenda uma consulta autenticada a `/api/transactions/check`. A liberação exige `COMPLETO`, tipo `DEPOSITO`, método `PIX`, valor exato e identificador correspondente. O valor do callback não é usado para liberar produtos. A consulta usa o `transactionId` da loja conforme a documentação, e compara o ID da Mistic retornado com o da criação. A criação de cobrança não é repetida automaticamente após timeout: o pedido fica `revisao` e é reconciliado, evitando cobranças duplicadas. Casos persistentes em revisão exigem conferência na Mistic pelo suporte.

Não existe botão que permita ao comprador marcar o pagamento como pago. Reembolsos confirmados pela consulta bloqueiam novos downloads; informações já baixadas não podem ser recuperadas. A loja não inicia reembolsos/saques pela API.

### Worker e Discord

`./iniciar-loja.sh` inicia a loja e `commerce_worker.py` juntos. Em produção, instale e habilite **também** `deploy/nzistore-worker.service`, usando o mesmo `/etc/nzistore.env` e a mesma chave/banco do serviço web. O worker consulta pagamentos pendentes e processa as notificações mesmo sem usuários com a página aberta. Sem ele, o botão **Já paguei · verificar** continua consultando o pagamento, mas webhooks e notificações não são processados em segundo plano.

Use webhook de um canal de texto privado no Discord. Não coloque a URL em JavaScript. Enviamos um evento por item quando o pagamento é confirmado (`aguardando`) e outro quando o item é entregue (`entregue`), com:

```json
{
  "email": "cliente@example.com",
  "id_product": 12,
  "product": "Pacote de Robux",
  "price": "90.00",
  "quantity": 1,
  "id_dacompra": "ID_DO_PEDIDO",
  "status": "aguardando",
  "nickname_roblox": "username",
  "robux_quantity": 1000,
  "event_id": "ID_DO_PEDIDO:ITEM:STATUS"
}
```

`price` é o total do item em reais, como string decimal; `status` é o status daquele item. Os dois campos de Roblox só aparecem em itens da categoria Robux. Conteúdo das entregas, senhas, CPF, chaves e mensagens do chat não são enviados. Menções são desabilitadas no Discord.

A fila é persistente e usa leases para vários workers. Falhas no Discord não desfazem pagamento/entrega; são repetidas com espera crescente. A entrega de notificações é *pelo menos uma vez*: em falha de rede depois do Discord aceitar a mensagem, pode haver repetição. `event_id` permite reconhecer duplicatas. Se nenhum webhook estiver configurado, os eventos ficam na fila para quando for configurado. O painel informa se as integrações estão configuradas e quantas notificações estão pendentes.

### Validação antes de ativar

Os testes automatizados usam banco temporário e respostas simuladas da Mistic/Discord, sem gerar cobranças reais. Cobrem propriedade dos pedidos, CSRF, mensagens, isolamento dos textos, download antes/depois do pagamento, valor e identidade da transação, callback falsificado, repetição, estoque concorrente, reposição, entrega manual, Roblox e falhas externas. A interface de estoque e chat também foi conferida em ambiente local isolado.

Ainda é necessário configurar credenciais, domínio HTTPS e worker, e validar uma cobrança real de baixo valor autorizada pelo responsável. A Mistic informa que não oferece sandbox. Referências: [Mistic Pay](https://docs.misticpay.com/) e [Discord Webhooks](https://docs.discord.com/developers/resources/webhook).

### Categorias e checkout
O painel permite editar o nome exibido e a imagem das categorias. As rotas e as chaves internas são preservadas, inclusive a validação obrigatória de destinatário dos produtos Robux. A vitrine inicial apresenta categorias em grade com bordas animadas (três colunas no desktop e duas no celular); a confirmação Roblox abre somente ao finalizar um carrinho que contenha Robux.

### Halloween e cupom
A identidade visual usa os arquivos locais `nzi-logo.png` e `halloween.gif`. O pop-up abre uma vez por sessão da aba e pode ser reaberto pelo botão Halloween. O GIF pode ser pausado e inicia oculto quando o navegador solicita movimento reduzido.
`DESCONTO10` começa com 10%, mas código, percentual (1–90%) e ativação podem ser alterados em **Admin → Cupons**. O pop-up e o carrinho consultam a configuração atual. Desativar o cupom oculta o pop-up; pedidos existentes mantêm o desconto original. Não há prazo nem limite por cliente configurados. O servidor calcula o desconto por unidade, arredondando a redução para baixo em centavos; os itens, o total do Pix e as notificações usam o valor líquido. O cupom e o desconto ficam registrados em `order_coupons`. O frontend nunca determina o preço aceito pelo servidor.

### Acesso administrativo e preferências
O login administrativo exige usuário, senha e PIN estático de seis dígitos em ambos os endpoints de login. Sessões anteriores à implementação do PIN não dão acesso administrativo. Configure localmente com `.venv/bin/flask --app server create-admin`; não envie segredos pelo chat. Um PIN estático complementa a senha, mas não substitui MFA com TOTP/WebAuthn.
As preferências de cookies são guardadas por 180 dias em cookie first-party, alteráveis pelo botão Cookies. A integração opcional UTMify respeita a escolha de análise de tráfego. A versão 2 do aviso reapresenta as preferências para explicar esse compartilhamento. O efeito de cursor não grava nem envia coordenadas e desliga com movimento reduzido ou ponteiro de toque.
Cada produto tem uma URL `/produto/<id>`, com preço real, descrição, modalidade de entrega e itens similares. Não há contadores de vendas, estoque ou avaliações fictícios.

### Dashboard e atendimento
O `/admin` reúne visão geral, vendas, conversas, produtos/estoque, categorias, clientes, cupom, integrações e segurança. Os períodos de 1, 7, 30 ou 90 dias usam o fuso de São Paulo. Faturamento e ticket médio consideram pedidos atualmente pagos, pelo momento da confirmação; pedidos reembolsados ficam excluídos. Aprovação é a proporção de pedidos pagos entre os pedidos criados no período, não conversão de visitantes. Visitas são registradas somente após aceitar análise de tráfego, uma vez por sessão de aba por dia; não representam pessoas únicas.
A central de conversas busca compradores por email ou ID do pedido e filtra atendimentos cuja última mensagem é do comprador. A conversa aberta consulta novas mensagens a cada 3 segundos; a lista atualiza a cada 3 segundos, somente com a aba visível. O envio preserva a chave de idempotência nas tentativas. Todas as métricas e listas exigem sessão administrativa; o cliente continua limitado aos próprios pedidos.
O menu lateral da vitrine começa recolhido. O botão de três barras abre a navegação, que pode ser fechada pelo botão, pelo fundo ou por Escape.


### Chat após a compra e relatório de emails
A API libera leitura, envio e presença no chat somente quando `paid_at` estiver preenchido por uma confirmação de pagamento. Apenas criar o pedido não libera atendimento. Compras posteriormente reembolsadas mantêm o suporte disponível. A lista administrativa só inclui compras confirmadas.
O bate-papo apresenta presença (expira em 15 segundos), indicador de digitação (5 segundos) e recibos de leitura. Enter envia e Shift+Enter quebra a linha. É atualização por consulta a cada 3 segundos, não WebSocket. O histórico fica no banco criptografado e continua isolado por comprador/pedido.
Em **Vendas → Gerar relatório de emails**, selecione até 366 dias e baixe um CSV UTF-8 com email, número de compras pagas e total pago em reais. Há uma linha por email, somente de pedidos atualmente pagos, usando data do pagamento e fuso de São Paulo. O download exige administrador, não usa cache e neutraliza fórmulas de planilha. Não envia campanhas de email.

### UTMify
Configure `UTMIFY_API_TOKEN` no ambiente **do servidor web e do worker** e reinicie ambos. O painel Integrações mostra apenas se a chave foi configurada, nunca seu conteúdo. Não coloque a chave em JavaScript nem em arquivo público. A integração faz POST para `https://api.utmify.com.br/api-credentials/orders` com `x-api-token`.
Eventos: Pix gerado (`waiting_payment`), confirmado (`paid`), falho (`refused`) e reembolsado (`refunded`). Usa fila persistente, tentativas com espera crescente e processamento sequencial por pedido para impedir que um evento pendente sobrescreva um pagamento confirmado. A entrega é pelo menos uma vez; o `orderId` é estável. Erros externos não desfazem o pagamento nem a entrega. Erros definitivos de credenciais/payload precisam ser corrigidos; não há reenvio histórico automático ao ativar.
O envio só é habilitado para pedidos criados com a opção **Análise de tráfego** aceita e com a integração configurada na geração dos eventos. `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `src` e `sck` são capturados da URL, limitados a 250 caracteres e preservados na sessão somente após essa escolha. Sem consentimento, não se enviam eventos à UTMify. Não são instalados scripts externos.
São enviados nome informado no pagamento, email da conta, itens, preços líquidos e datas UTC. CPF e telefone são `null`; não se inventam documentos. A comissão é informada pelo valor bruto recebido (sem taxas conhecidas), com taxa de gateway zero; por isso não representa lucro líquido. Mensagens, conteúdo das entregas e tokens não integram o payload.
A integração foi validada com respostas simuladas; a aceitação pela conta UTMify ainda precisa ser conferida após configurar a credencial. Não houve transmissão de dados reais nos testes. Ao atualizar uma instalação, pare o worker antigo antes de carregar a versão web nova e depois reinicie o worker, pois ele precisa reconhecer o novo tipo de tarefa.

### Nome de usuário
O cadastro continua pedindo somente email e senha. O nome exibido é derivado da parte do email anterior ao `@`, normalizado para letras ASCII, números, ponto, hífen e sublinhado (3–32 caracteres). Contas existentes recebem um perfil automaticamente. É um nome de exibição, não um identificador único nem uma nova credencial de login.
`Minha conta` exibe apenas o nome e email do próprio usuário autenticado. A alteração do nome exige sessão e CSRF, é persistida no banco criptografado e permite uma mudança a cada 24 horas. A verificação e a atualização ocorrem na mesma transação para evitar alterações concorrentes. Reenviar o mesmo nome não consome o prazo; mudanças bloqueadas retornam HTTP 429 com `Retry-After`. O login permanece pelo email.

### Jogos Roblox e mapa geográfico
A categoria passa a se chamar **Roblox**, com entrada em `/roblox`; o endereço antigo continua funcionando. Em **Categorias → Jogos / subcategorias Roblox**, cadastre nome e imagem dos jogos. Em Produtos, escolha Roblox e o jogo. Cada jogo recebe uma página `/roblox/<slug>`. Produtos antigos sem jogo ficam em “Outros produtos Roblox”. Para excluir um jogo, mova primeiro seus produtos.

O dashboard inclui visitas diárias, compradores de primeira compra e recorrentes, aprovação e produtos mais vendidos. Recorrentes são compradores do período com mais de um pedido atualmente pago até o fim do período. O mapa usa a [malha simplificada oficial do IBGE](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3), armazenada localmente em `static/brazil-states.json`.

Para localizar visitas por estado, configure `GEOIP_DATABASE_PATH` com o caminho absoluto de uma base local MaxMind City `.mmdb` e reinicie o servidor. Sem base, as visitas continuam contabilizadas, mas aparecem sem localização. Não há consulta de IP a serviço externo. Atrás de proxy, configure `GEOIP_TRUSTED_PROXIES` apenas com os CIDRs dos proxies que você controla e faça o proxy sobrescrever `X-Real-IP` com o IP real validado. Cabeçalhos de clientes não são confiados por padrão.

Os registros de visitas guardam dia, identificador HMAC diário, país e estado aproximados, por até 180 dias; não guardam IP bruto. Isso não altera eventuais logs de acesso do servidor/proxy. A coleta para quando a preferência de análise é revogada. Dados históricos não são reconstruídos.

### Recuperação de senha e celebração de cupom
Em Minha conta, **Esqueci minha senha** envia um código para clientes com email verificado, usando o SMTP configurado. O código fica apenas como HMAC no banco, expira em 10 minutos, permite até cinco tentativas e é consumido uma única vez. O envio tem limite por email e IP. Concluir encerra as sessões existentes. Administradores continuam usando o fluxo administrativo. Os testes usam envio simulado, sem emails reais.
Copiar e aplicar cupom dispara confete local por 2,2 segundos, respeitando movimento reduzido. O checkout contém aceite explícito com o link de termos fornecido pelo responsável (`/terms`). A integração Pantera Pay aguarda sua documentação; as cobranças existentes continuam no fluxo Mistic.

### Pantera Pay
Configure `PAYMENT_PROVIDER=pantera` e `PANTERA_API_KEY` somente no `.env` do servidor e reinicie web e worker. Novos Pix usam POST `/transactions` com valor inteiro em centavos (mínimo R$ 0,50), sem CPF. O checkout pede email e confirmação de email para contato, sem nome completo e sem envio desses campos à Pantera. O QR usa o código copia-e-cola retornado. Não são usados saques, split nem consulta de saldo.
Cada cobrança registra o provedor; cobranças Mistic anteriores continuam consultadas pela Mistic e precisam das chaves antigas. Consulta Pantera: GET `/transactions/:id?nocache=1`, conferindo ID, valor, tipo DEPOSIT e motivo PIX_PAYMENT antes de liberar entrega. Webhook por cobrança usa URL com token e apenas agenda consulta autenticada; seu corpo nunca confirma pagamento. Em localhost, o webhook é omitido; use o worker ou “Já paguei” para consultar. Em HTTPS público ele é enviado automaticamente.
A documentação fornecida não define idempotência nem consulta por referência própria: falha/timeout de criação mantém o pedido em revisão e não gera nova cobrança automaticamente. Não tente recriar cobranças sem conferir o painel do provedor. Credenciais precisam de payments.create e payments.read; webhooks.manage não é utilizado. Testes usam respostas simuladas, sem cobranças reais.

### Tela de pagamento Pix
Ao clicar em Pagar, o checkout cria o pedido e abre `/pagamento/<id>`, que gera o Pix uma única vez. A tela exibe valor, produtos, QR Code local e código copiável; consulta o pagamento a cada 10 segundos enquanto está visível e mostra confirmação com confete. Falhas de criação continuam em revisão, sem nova cobrança automática. Pedidos anteriores também oferecem “Abrir pagamento com QR Code”.
O endpoint autenticado `/api/orders/<id>/pix.png` exige acesso ao pedido, só responde enquanto o Pix está pendente e não usa cache. O QR é gerado pelo pacote qrcode a partir do copia-e-cola, sem serviços externos. A documentação Pantera fornecida não tem campo de nome/descrição da transação: o nome dos produtos é mostrado na loja, mas alterar o “N/A” do painel Pantera exige orientação do provedor.

### Limite e prazo do Pix
Um cliente só pode ter uma cobrança em criação, pendente ou revisão por vez. A criação usa transação no banco para bloquear tentativas concorrentes, devolve HTTP 429 com Retry-After e aponta o pedido ativo. Reabrir o mesmo pedido reutiliza a cobrança. Há no máximo quatro gerações por cliente em uma hora, além do limite de requisições.
O prazo de exibição do Pix na loja é de 15 minutos, persistido em payment_started_at/pix_expires_at. Após esse prazo, pendentes passam a Expirado, sem QR/código disponível. O pedido expirado não gera outro Pix; o cliente pode criar um novo pedido. Cobranças em revisão continuam bloqueando outra geração porque sua criação pode ter ocorrido no banco do provedor. A expiração local não cancela a cobrança bancária: a documentação fornecida não tem cancelamento nem parâmetro de validade. Pagamentos tardios autenticados continuam sendo reconhecidos. Pedidos anteriores sem prazo recebem 15 minutos na atualização.
A página de pedidos mostra status e botão para abrir o pagamento; QR e copia-e-cola aparecem apenas na tela /pagamento.

### E-mail e termos no Pix
O checkout Pantera solicita apenas email e confirmação, comparados sem diferença entre maiúsculas/minúsculas. O aceite inicia desmarcado. A API de criação de pagamento exige `payer_email`, `payer_email_confirmation` iguais e `terms_accepted: true`, registrando data e caminho `/terms` em payment_terms. Dados salvos para geração automática após o checkout ficam vinculados ao ID daquele pedido; outro pedido exige novo aceite. A integração Mistic legada ainda exige nome no seu endpoint; os novos pagamentos usam Pantera.
