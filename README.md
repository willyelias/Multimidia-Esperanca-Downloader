# 🎬 Multimídia Esperança Downloader (v2.0)

🌐 **Site Online:** [https://multimidiadownloadesperanca.netlify.app](https://multimidiadownloadesperanca.netlify.app)

Aplicativo completo (**Desktop Windows `.exe` em Python/CustomTkinter** + **Aplicação Web Serverless no Netlify**) para baixar vídeos e áudios do YouTube, TikTok, Instagram, Facebook, X/Twitter, Vimeo e dezenas de outros sites, além de converter e recortar arquivos de mídia.

---

## ✨ Novidades e Otimizações (v2.0)

1. **Suporte a Playlists Completas**: Escolha entre baixar apenas o **Vídeo Único** ou expandir uma **Playlist Completa** automaticamente na fila com miniaturas e progresso individual.
2. **Cookies Automáticos do Navegador**: Extraia a sessão diretamente do **Chrome, Edge, Firefox, Brave ou Opera** instalados no PC (`--cookies-from-browser`) sem precisar exportar arquivos `.txt` manualmente (mantendo também a opção manual `.txt`).
3. **Recorte de Trecho de Vídeo/Áudio (`✂️ Cortar Trecho`)**: Defina o tempo inicial (ex: `00:01:00`) e final (ex: `00:02:30`) para baixar apenas o trecho desejado usando `--download-sections`.
4. **Histórico Persistente & Barra de Status Visível**:
   - Aba **📜 Histórico** com todos os downloads concluídos, botões para reproduzir (`▶`), abrir na pasta (`📂`) ou baixar novamente (`🔄`).
   - Barra de progresso visível no rodapé mostrando o download e instalação automática do `yt-dlp.exe` e `ffmpeg.exe`.
5. **Correções de Estabilidade (Thread-Safety)**:
   - Todas as atualizações de interface gráfica no CustomTkinter agora são executadas de forma segura via `self.after(0, ...)`, eliminando travamentos durante downloads simultâneos.
   - Conversor local FFmpeg agora exibe a **porcentagem real (0% a 100%)** calculada em tempo real a partir da duração do arquivo.
6. **Versão Web Online (Pronta para Netlify)**:
   - Interface Web responsiva em `web/` com **Netlify Serverless Functions** (`netlify/functions/video-info.mjs` e `netlify/functions/download.mjs`) e **Conversor/Recortador de Áudio no Navegador** via Web Audio API.

---

## 🖥️ Como Executar a Versão Desktop (Python)

### Pré-requisitos
- Python 3.10+ instalado no Windows.

### Instalação e Execução
```bash
git clone https://github.com/willyelias/Multimidia-Esperanca-Downloader.git
cd Multimidia-Esperanca-Downloader
pip install -r requirements.txt
python app.py
```
*(Na primeira abertura, o programa baixará automaticamente o `yt-dlp.exe` e o `ffmpeg.exe` na pasta `~/.yt_downloader_pro/bin` exibindo o progresso na barra inferior).*

### Gerar Executável (`.exe`) para Windows
```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name "YTDownloaderUltimate" app.py
```

---

## 🌐 Como Publicar Online no Netlify

Este repositório já está pré-configurado com o arquivo [`netlify.toml`](./netlify.toml), front-end em [`web/`](./web) e funções serverless em [`netlify/functions/`](./netlify/functions).

1. Acesse o painel do **[Netlify](https://app.netlify.com/)**.
2. Clique em **Add new site** ➔ **Import an existing project**.
3. Escolha **GitHub** e selecione o repositório **`willyelias/Multimidia-Esperanca-Downloader`**.
4. O Netlify detectará automaticamente as configurações do `netlify.toml`:
   - **Publish directory**: `web`
   - **Functions directory**: `netlify/functions`
5. Clique em **Deploy site** — seu site estará online em poucos segundos!

---

## 📂 Estrutura do Projeto

```text
Multimidia-Esperanca-Downloader/
├── app.py                        # Ponto de entrada principal (Desktop)
├── requirements.txt              # Dependências Python (CustomTkinter, yt-dlp, Pillow, etc.)
├── netlify.toml                  # Configuração de Deploy e Serverless do Netlify
├── package.json                  # Configuração Node.js para Netlify Functions
├── desktop/
│   ├── app.py                    # Código-fonte completo e otimizado do App Desktop
│   └── requirements.txt          # Dependências Python
├── netlify/
│   └── functions/
│       ├── video-info.mjs        # API Serverless para buscar título, capa e metadados
│       └── download.mjs          # API Serverless para resolver streams MP4/MP3
└── web/
    ├── index.html                # Interface Web Online
    ├── styles.css                # Tema Dark (Verde #2CC985 / Azul #3B8ED0)
    └── app.js                    # Lógica da fila, histórico e conversor Web Audio
```
