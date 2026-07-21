# Como configurar a atualização automática

Este documento é o passo a passo do que **você** precisa fazer (são coisas
ligadas à sua conta Google e ao GitHub, que eu não consigo fazer por você).
Depois disso, a atualização dos dados passa a ser automática.

Leva uns 20-30 minutos na primeira vez. Depois disso, nunca mais precisa mexer.

---

## Parte 1 — Criar a "conta de serviço" no Google (o robô leitor)

Isso cria um usuário especial que só tem permissão de **leitura** na pasta
do Drive — ele não pode editar, apagar, nem ver mais nada além do que você
compartilhar com ele.

1. Acesse **https://console.cloud.google.com/** com a sua conta Google pessoal.
2. No topo, clique em **"Selecionar projeto" → "Novo projeto"**.
   - Nome: `qualitti-painel` (ou o que preferir)
   - Clique em **Criar**.
3. Com o projeto selecionado, no menu lateral vá em
   **"APIs e serviços" → "Biblioteca"**.
   - Procure por **"Google Drive API"** → clique → **Ativar**.
4. Ainda em "APIs e serviços", vá em **"Credenciais"**.
   - Clique em **"+ Criar credenciais" → "Conta de serviço"**.
   - Nome: `qualitti-leitor`
   - Clique em **Concluir** (não precisa dar nenhuma permissão especial aqui).
5. Na lista de contas de serviço, clique na que você acabou de criar.
   - Vá na aba **"Chaves"** → **"Adicionar chave" → "Criar nova chave"** →
     tipo **JSON** → **Criar**.
   - Isso baixa um arquivo `.json` pro seu computador. **Guarde esse arquivo**
     — ele será colado no GitHub daqui a pouco (Parte 3).
6. Copie o **e-mail** dessa conta de serviço — algo como
   `qualitti-leitor@qualitti-painel-123456.iam.gserviceaccount.com`
   (aparece na mesma tela, ou dentro do arquivo `.json` no campo `client_email`).

---

## Parte 2 — Compartilhar a pasta do Drive com o robô

1. Abra o **Google Drive**, encontre a pasta onde ficam as planilhas
   (a que sincroniza do seu PC).
2. Botão direito na pasta → **Compartilhar**.
3. Cole o e-mail da conta de serviço (o que você copiou no passo 6 acima).
4. Permissão: **Leitor** (Viewer). Não precisa notificar por e-mail.
5. Clique em **Enviar/Compartilhar**.
6. Copie o **ID da pasta**: abra a pasta no navegador e olhe a URL —
   é o trecho depois de `/folders/`:
   `https://drive.google.com/drive/folders/`**`1AbCdEfGhIjKlMnOpQrStUvWxYz`**
   Guarde esse ID.

---

## Parte 3 — Criar o repositório no GitHub

1. Acesse **https://github.com** e crie uma conta, se ainda não tiver.
2. Clique em **"New repository"**.
   - Nome: `qualitti-zootecnico` (ou o que preferir)
   - Marque como **Public** (necessário para o GitHub Pages gratuito)
   - Clique em **Create repository**.
3. Suba os arquivos desta pasta (`qualitti-deploy/`) para esse repositório.
   - Mais fácil: pelo site do GitHub, arraste os arquivos e pastas na tela
     inicial do repositório ("uploading an existing file").
   - Mantenha a estrutura de pastas exatamente como está
     (`data/`, `scripts/`, `.github/workflows/`, `index.html`, `logo.png`).

4. Agora, configure os **"segredos"** (as credenciais ficam guardadas de
   forma criptografada, ninguém vê):
   - No repositório, vá em **Settings → Secrets and variables → Actions**.
   - Clique em **"New repository secret"** duas vezes, para criar:
     - `GDRIVE_FOLDER_ID` → cole o ID da pasta (Parte 2, passo 6)
     - `GDRIVE_SERVICE_ACCOUNT_KEY` → abra o arquivo `.json` que baixou na
       Parte 1 num bloco de notas, copie **todo o conteúdo** e cole aqui.

5. Ative o **GitHub Pages**:
   - Vá em **Settings → Pages**.
   - Em "Source", selecione **"Deploy from a branch"** → branch `main` →
     pasta `/ (root)` → **Save**.
   - Depois de alguns minutos, o site fica disponível em algo como
     `https://SEU_USUARIO.github.io/qualitti-zootecnico/`.

---

## Parte 4 — Testar a atualização

1. No repositório, vá na aba **"Actions"**.
2. Clique no workflow **"Atualizar dados do painel"**.
3. Clique em **"Run workflow"** (botão à direita) para rodar uma vez manualmente.
4. Aguarde uns 1-2 minutos e veja se terminou com o ícone verde (sucesso).
   - Se der erro (ícone vermelho), clique nele pra ver a mensagem — me manda
     print que eu te ajudo a resolver.
5. Se deu certo, os arquivos em `data/` no repositório terão sido atualizados
   automaticamente, e o site (no link do GitHub Pages) já reflete os dados novos.

Depois disso, ele roda sozinho **todo dia às 6h da manhã**. Se quiser forçar
uma atualização na hora (por exemplo, depois de lançar a mortalidade do dia),
é só repetir o passo 3 (Run workflow).

---

## O que fazer quando quiser atualizar uma planilha

Simples: só substitua o arquivo na pasta do Drive (mesmo nome ou nome
diferente, não importa — o robô identifica pela aba interna da planilha).
No próximo ciclo (automático às 6h, ou manual pelo botão), o site já reflete
os dados novos. Você não precisa mais me mandar a planilha.

---

## Dúvidas frequentes

**"E se eu errar algum passo?"** Sem problema, nada aqui é destrutivo — pode
refazer uma etapa quantas vezes precisar.

**"O robô pode estragar algo na minha pasta?"** Não. A permissão dada é só de
**leitura** — ele não consegue editar, mover ou apagar nada no seu Drive.

**"Quem consegue ver o site?"** Por enquanto, qualquer pessoa com o link
(como conversamos, essa é uma limitação do GitHub Pages gratuito). Deixamos
para depois a decisão de restringir por login, se for necessário.
