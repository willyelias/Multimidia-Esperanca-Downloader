import sys
import subprocess
import os
import shutil
import threading
import re
import json
from datetime import datetime
from time import sleep
from io import BytesIO
import tkinter as tk
from tkinter import filedialog, messagebox

import requests
import zipfile
import customtkinter as ctk
from PIL import Image
from plyer import notification


# --- FUNÇÃO MÁGICA PARA RECURSOS (Ícone no .exe) ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def validar_tempo_corte(valor: str) -> str:
    """
    Valida e normaliza uma string de tempo (ex: '1:30', '00:01:30', '90')
    Retorna string limpa ou levanta ValueError se inválido.
    """
    v = valor.strip()
    if not v:
        return ""
    if re.match(r"^\d+(\.\d+)?$", v):
        return v
    if re.match(r"^(\d{1,2}:)?\d{1,2}:\d{2}(\.\d+)?$", v):
        return v
    raise ValueError(f"Formato de tempo inválido: '{valor}'. Use MM:SS ou HH:MM:SS.")


def tempo_para_segundos(tempo_str: str) -> float:
    """Converte HH:MM:SS.xx ou MM:SS para segundos."""
    partes = tempo_str.strip().split(":")
    if len(partes) == 3:
        return int(partes[0]) * 3600 + int(partes[1]) * 60 + float(partes[2])
    elif len(partes) == 2:
        return int(partes[0]) * 60 + float(partes[1])
    return float(partes[0])


# Configuração Visual
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")


class DownloadItem(ctk.CTkFrame):
    """Card individual da fila de downloads (Thread-Safe)."""

    def __init__(
        self,
        master,
        url,
        folder,
        tools_path,
        mode,
        quality,
        subs,
        auth_config=None,
        trim_range=None,
        prefetched_info=None,
        on_complete_callback=None,
        ytdlp_ready_event=None,
        ffmpeg_ready_event=None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.url = url
        self.folder = folder
        self.tools_path = tools_path
        self.mode = mode  # "audio" | "video"
        self.quality = quality
        self.subs = subs
        self.auth_config = auth_config or {"type": "none", "value": None}
        self.trim_range = trim_range  # (start_str, end_str) ou None
        self.prefetched_info = prefetched_info
        self.on_complete_callback = on_complete_callback
        self.ytdlp_ready_event = ytdlp_ready_event
        self.ffmpeg_ready_event = ffmpeg_ready_event

        self.processo = None
        self.is_cancelled = False
        self.final_absolute_path = None
        self.title_text = (
            prefetched_info.get("title", url) if prefetched_info else url
        )

        self.grid_columnconfigure(1, weight=1)

        # --- DEFINIÇÃO DE CORES ---
        # Áudio = Azul (#3B8ED0), Vídeo = Verde (#2CC985)
        if mode == "audio":
            icon_mode = "🎵"
            self.color_mode = "#3B8ED0"
        else:
            icon_mode = "🎬"
            self.color_mode = "#2CC985"

        trim_badge = ""
        if self.trim_range and (self.trim_range[0] or self.trim_range[1]):
            ini = self.trim_range[0] or "00:00"
            fim = self.trim_range[1] or "fim"
            trim_badge = f" ✂️[{ini}-{fim}]"

        self.info_prefix = (
            f"[{icon_mode} MP3{trim_badge}]"
            if mode == "audio"
            else f"[{icon_mode} {quality}{trim_badge}]"
        )

        # 1. Capa (Thumbnail)
        self.lbl_thumb = ctk.CTkLabel(
            self, text="...", width=96, height=54, fg_color="#222222", corner_radius=6
        )
        self.lbl_thumb.grid(row=0, column=0, rowspan=3, padx=10, pady=8)

        # 2. Informações de Texto
        self.lbl_info = ctk.CTkLabel(
            self,
            text=f"{self.info_prefix} Aguardando início...",
            anchor="w",
            font=("Segoe UI", 11),
            text_color="gray",
        )
        self.lbl_info.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(6, 0))

        initial_title = (
            self.title_text[:65] + "..."
            if len(self.title_text) > 65
            else self.title_text
        )
        self.lbl_title = ctk.CTkLabel(
            self,
            text=initial_title if prefetched_info else "Obtendo informações...",
            anchor="w",
            font=("Segoe UI", 12, "bold"),
        )
        self.lbl_title.grid(row=1, column=1, sticky="ew", padx=(0, 10))

        # 3. Barra de Progresso
        self.progress = ctk.CTkProgressBar(self, height=8)
        self.progress.configure(progress_color=self.color_mode)
        self.progress.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=(5, 10))
        self.progress.set(0)

        # 4. Botões (Cancelar, Play, Pasta)
        self.frame_btns = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_btns.grid(row=0, column=2, rowspan=3, padx=10)

        self.btn_cancel = ctk.CTkButton(
            self.frame_btns,
            text="✕",
            width=32,
            height=32,
            fg_color="transparent",
            text_color="gray",
            hover_color="#444",
            command=self.cancelar_download,
        )
        self.btn_cancel.pack(side="right")

        # Botões ocultos até terminar
        self.btn_play = ctk.CTkButton(
            self.frame_btns,
            text="▶",
            width=32,
            height=32,
            fg_color="#2CC985",
            text_color="#051b11",
            hover_color="#229e68",
            command=self.reproduzir_arquivo,
        )
        self.btn_folder = ctk.CTkButton(
            self.frame_btns,
            text="📂",
            width=32,
            height=32,
            fg_color="#2B2B2B",
            text_color="white",
            hover_color="#444444",
            command=self.abrir_local_arquivo,
        )

    def carregar_thumbnail(self, url_thumb):
        def _load():
            try:
                if not url_thumb or self.is_cancelled:
                    return
                headers = {"User-Agent": "Mozilla/5.0"}
                response = requests.get(url_thumb, headers=headers, timeout=6)
                response.raise_for_status()
                img = Image.open(BytesIO(response.content))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(96, 54))
                if not self.is_cancelled:
                    self.after(0, lambda: self.lbl_thumb.configure(image=ctk_img, text=""))
            except Exception:
                pass

        threading.Thread(target=_load, daemon=True).start()

    def cancelar_download(self):
        self.is_cancelled = True
        if self.processo and self.processo.poll() is None:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.processo.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    self.processo.kill()
            except Exception:
                pass
        self.pack_forget()
        self.destroy()

    def reproduzir_arquivo(self):
        if self.final_absolute_path and os.path.exists(self.final_absolute_path):
            try:
                if sys.platform == "win32":
                    os.startfile(self.final_absolute_path)
                elif sys.platform == "darwin":
                    subprocess.run(["open", self.final_absolute_path])
                else:
                    subprocess.run(["xdg-open", self.final_absolute_path])
            except Exception as e:
                messagebox.showerror("Erro Player", f"Não foi possível abrir o arquivo:\n{e}")
        else:
            messagebox.showerror("Erro", "Arquivo não encontrado no disco.")

    def abrir_local_arquivo(self):
        if sys.platform == "win32":
            try:
                if self.final_absolute_path and os.path.exists(self.final_absolute_path):
                    subprocess.run(
                        ["explorer", "/select,", os.path.normpath(self.final_absolute_path)]
                    )
                else:
                    os.startfile(self.folder)
            except Exception:
                os.startfile(self.folder)
        else:
            try:
                subprocess.run(["xdg-open", self.folder])
            except Exception:
                pass

    def start(self):
        thread = threading.Thread(target=self._logic_completa, daemon=True)
        thread.start()

    def _update_ui(
        self,
        percent,
        status_text,
        finished=False,
        final_path=None,
        title=None,
        color=None,
    ):
        """Agenda atualização segura na thread principal do Tkinter."""
        if self.is_cancelled:
            return

        def _apply():
            if self.is_cancelled or not self.winfo_exists():
                return
            self.progress.set(max(0.0, min(1.0, float(percent))))
            self.lbl_info.configure(text=f"{self.info_prefix} {status_text}")
            if color:
                self.lbl_info.configure(text_color=color)

            if title:
                self.title_text = title
                display_title = title[:65] + "..." if len(title) > 65 else title
                self.lbl_title.configure(text=display_title)

            if final_path:
                self.final_absolute_path = final_path

            if finished:
                self.btn_cancel.pack_forget()
                self.btn_folder.pack(side="right", padx=2)
                self.btn_play.pack(side="right", padx=2)
                try:
                    notification.notify(
                        title="Download Concluído!",
                        message=f"{self.title_text[:80]}",
                        app_name="Youtube Downloader Ultimate",
                        timeout=4,
                    )
                except Exception:
                    pass

                if self.on_complete_callback:
                    self.on_complete_callback(
                        {
                            "title": self.title_text,
                            "url": self.url,
                            "mode": self.mode,
                            "quality": "MP3 320kbps" if self.mode == "audio" else self.quality,
                            "path": self.final_absolute_path,
                            "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        }
                    )

        self.after(0, _apply)

    def gerar_nome_unico(self, base_filename):
        """Gera 'Arquivo (1).mp4' se 'Arquivo.mp4' já existir."""
        nome, ext = os.path.splitext(base_filename)
        contador = 1
        novo_nome = base_filename
        while os.path.exists(os.path.join(self.folder, novo_nome)):
            novo_nome = f"{nome} ({contador}){ext}"
            contador += 1
        return novo_nome

    def _get_auth_args(self):
        """Retorna argumentos de autenticação (cookies do navegador ou arquivo txt)."""
        auth_type = self.auth_config.get("type", "none")
        auth_val = self.auth_config.get("value")
        if auth_type == "browser" and auth_val:
            return ["--cookies-from-browser", auth_val]
        elif auth_type == "file" and auth_val and os.path.exists(auth_val):
            return ["--cookies", auth_val]
        return []

    def _logic_completa(self):
        try:
            clean_url = self.url.split("?turnstile")[0].strip()
            ext_final = "mp3" if self.mode == "audio" else "mp4"
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

            # Aguarda na fila caso o yt-dlp ainda esteja baixando
            if self.ytdlp_ready_event and not self.ytdlp_ready_event.is_set():
                self._update_ui(0.01, "⏳ Na fila (Aguardando yt-dlp finalizar download)...")
                while not self.ytdlp_ready_event.wait(0.3):
                    if self.is_cancelled:
                        return

            yt_dlp_bin = self.tools_path.get("yt-dlp")
            while (not yt_dlp_bin or not os.path.exists(yt_dlp_bin)) and not self.is_cancelled:
                self._update_ui(0.01, "⏳ Na fila (Aguardando yt-dlp)...")
                sleep(0.5)
                yt_dlp_bin = self.tools_path.get("yt-dlp")

            if self.is_cancelled:
                return

            # 1. OBTENÇÃO DE METADADOS (Já carrega título e capa enquanto o FFmpeg baixa!)
            if self.prefetched_info and self.prefetched_info.get("title"):
                self.title_text = self.prefetched_info["title"]
                thumb_url = self.prefetched_info.get("thumbnail")
                if thumb_url:
                    self.carregar_thumbnail(thumb_url)
                self._update_ui(0.05, "Preparando download...", title=self.title_text)
            else:
                self._update_ui(0.02, "Obtendo metadados do vídeo...")
                cmd_info = [
                    yt_dlp_bin,
                    "--dump-json",
                    "--no-playlist",
                    "--no-warnings",
                    clean_url,
                ] + self._get_auth_args()

                res = subprocess.run(
                    cmd_info,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creation_flags,
                )

                # Fallback: se falhar por bloqueio do banco de cookies do navegador aberto, tenta sem cookies
                if res.returncode != 0 and self.auth_config.get("type") == "browser":
                    cmd_info_no_cookie = [
                        yt_dlp_bin,
                        "--dump-json",
                        "--no-playlist",
                        "--no-warnings",
                        clean_url,
                    ]
                    res_retry = subprocess.run(
                        cmd_info_no_cookie,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        creationflags=creation_flags,
                    )
                    if res_retry.returncode == 0:
                        res = res_retry
                        self.auth_config = {"type": "none", "value": None}

                if res.returncode != 0:
                    err_lines = [
                        l for l in (res.stderr or res.stdout).splitlines() if "ERROR:" in l
                    ]
                    err_msg = (
                        err_lines[-1].replace("ERROR:", "").strip()[:70]
                        if err_lines
                        else "Link inválido ou vídeo privado (use Cookies)."
                    )
                    raise RuntimeError(err_msg)

                json_line = ""
                for line in res.stdout.splitlines():
                    if line.strip().startswith("{"):
                        json_line = line.strip()
                        break

                if not json_line:
                    raise RuntimeError("Não foi possível ler os dados do vídeo.")

                info = json.loads(json_line)
                self.title_text = info.get("title") or "Video_Sem_Titulo"
                thumb_url = info.get("thumbnail")

                if thumb_url:
                    self.carregar_thumbnail(thumb_url)
                self._update_ui(0.05, "Preparando arquivo...", title=self.title_text)

            # Aguarda na fila caso o FFmpeg ainda esteja sendo baixado na barra inferior
            if self.ffmpeg_ready_event and not self.ffmpeg_ready_event.is_set():
                self._update_ui(
                    0.06,
                    "⏳ Na fila (Aguardando download do FFmpeg concluir)...",
                    title=self.title_text,
                )
                while not self.ffmpeg_ready_event.wait(0.3):
                    if self.is_cancelled:
                        return

            # 2. CÁLCULO DE NOME ÚNICO E SEGURO PARA WINDOWS
            base_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", self.title_text).strip()
            base_name = base_name.rstrip(". ")[:150] or "video_download"
            if self.trim_range and (self.trim_range[0] or self.trim_range[1]):
                base_name += "_recorte"

            nome_correto = f"{base_name}.{ext_final}"
            nome_final_unico = self.gerar_nome_unico(nome_correto)
            stem_unico = os.path.splitext(nome_final_unico)[0]

            # Usa template com %(ext)s para que o yt-dlp gerencie corretamente arquivos temporários e conversão
            output_template = os.path.join(self.folder, f"{stem_unico}.%(ext)s")
            path_final_esperado = os.path.join(self.folder, nome_final_unico)
            self.final_absolute_path = path_final_esperado

            # 3. MONTAGEM DO COMANDO DE DOWNLOAD
            cmd_down = [
                yt_dlp_bin,
                "--newline",
                "--no-playlist",
                "--no-mtime",
                "-o",
                output_template,
            ] + self._get_auth_args()

            if self.mode == "audio":
                cmd_down.extend(
                    [
                        "-x",
                        "--audio-format",
                        "mp3",
                        "--audio-quality",
                        "0",
                        "--embed-thumbnail",
                        "--add-metadata",
                    ]
                )
            else:
                cmd_down.extend(["--merge-output-format", "mp4"])
                if "4K" in self.quality:
                    cmd_down.extend(
                        ["--format", "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best"]
                    )
                elif "1080p" in self.quality:
                    cmd_down.extend(
                        ["--format", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"]
                    )
                elif "720p" in self.quality:
                    cmd_down.extend(
                        ["--format", "bestvideo[height<=720]+bestaudio/best[height<=720]/best"]
                    )
                elif "480p" in self.quality:
                    cmd_down.extend(
                        ["--format", "bestvideo[height<=480]+bestaudio/best[height<=480]/best"]
                    )
                else:
                    cmd_down.extend(["--format", "bestvideo+bestaudio/best"])

            if self.subs and self.mode != "audio":
                cmd_down.extend(
                    [
                        "--write-subs",
                        "--write-auto-subs",
                        "--sub-lang",
                        "pt.*,en.*",
                        "--embed-subs",
                    ]
                )

            # Recorte de trecho de vídeo/áudio (Início / Fim)
            if self.trim_range and (self.trim_range[0] or self.trim_range[1]):
                ini = self.trim_range[0] if self.trim_range[0] else "0"
                fim = self.trim_range[1] if self.trim_range[1] else "inf"
                cmd_down.extend(
                    [
                        "--download-sections",
                        f"*{ini}-{fim}",
                        "--force-keyframes-at-cuts",
                    ]
                )

            ffmpeg_bin = self.tools_path.get("ffmpeg")
            if ffmpeg_bin and os.path.exists(ffmpeg_bin):
                cmd_down.extend(["--ffmpeg-location", os.path.dirname(ffmpeg_bin)])

            cmd_down.append(clean_url)

            # 4. EXECUÇÃO COM LEITURA EM TEMPO REAL
            self.processo = subprocess.Popen(
                cmd_down,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creation_flags,
                encoding="utf-8",
                errors="replace",
            )

            last_err_line = ""
            for line in self.processo.stdout:
                if self.is_cancelled:
                    break
                line_s = line.strip()
                if "ERROR:" in line_s:
                    last_err_line = line_s

                match = re.search(r"\[download\]\s+(\d+\.?\d*)%", line_s)
                if match:
                    pct = float(match.group(1))
                    # Velocidade e ETA opcionais
                    speed_m = re.search(r"at\s+([0-9.]+[A-Za-z/]+)", line_s)
                    speed_txt = f" ({speed_m.group(1)})" if speed_m else ""
                    self._update_ui(pct / 100.0, f"Baixando: {pct:.1f}%{speed_txt}")
                elif "[ExtractAudio]" in line_s or (
                    "Destination:" in line_s and ".mp3" in line_s
                ):
                    self._update_ui(0.98, "Convertendo para MP3...")
                elif "[Merger]" in line_s or "Merging formats" in line_s:
                    self._update_ui(0.98, "Unindo Vídeo e Áudio (MP4)...")
                elif "[ModifyChapters]" in line_s or "download-sections" in line_s:
                    self._update_ui(0.95, "Recortando trecho selecionado...")

            self.processo.wait()

            if self.is_cancelled:
                return

            # Verifica o arquivo final gerado
            if not os.path.exists(path_final_esperado):
                # Procura se o yt-dlp gerou com outra extensão por falta de ffmpeg ou similar
                for ext_cand in [ext_final, "mp4", "mkv", "webm", "mp3", "m4a"]:
                    cand = os.path.join(self.folder, f"{stem_unico}.{ext_cand}")
                    if os.path.exists(cand):
                        path_final_esperado = cand
                        break

            if self.processo.returncode == 0 and os.path.exists(path_final_esperado):
                self._update_ui(
                    1.0,
                    "Concluído!",
                    finished=True,
                    final_path=path_final_esperado,
                    color=self.color_mode,
                )
            else:
                msg = (
                    last_err_line.replace("ERROR:", "").strip()[:60]
                    if last_err_line
                    else "Falha no download (Verifique Cookies/Login)"
                )
                self._update_ui(0, f"Erro: {msg}", color="#EF4444")

        except Exception as e:
            if not self.is_cancelled:
                self._update_ui(0, f"Erro: {str(e)[:65]}", title="Falha no Download", color="#EF4444")


class ConverterItem(ctk.CTkFrame):
    """Card individual da fila de conversão com barra de progresso real."""

    def __init__(
        self,
        master,
        filepath,
        output_folder,
        tools_path,
        target_format,
        ffmpeg_ready_event=None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.filepath = filepath
        self.output_folder = output_folder
        self.tools = tools_path
        self.target_format = target_format
        self.ffmpeg_ready_event = ffmpeg_ready_event
        self.grid_columnconfigure(1, weight=1)

        # Cores para o conversor
        if target_format in ("mp3", "wav"):
            icon = "🎵"
            self.color = "#3B8ED0"  # Azul
        else:
            icon = "🎬"
            self.color = "#2CC985"  # Verde

        filename = os.path.basename(filepath)
        self.lbl_icon = ctk.CTkLabel(
            self, text=icon, width=45, height=45, fg_color="#222222", corner_radius=6, font=("Segoe UI", 20)
        )
        self.lbl_icon.grid(row=0, column=0, rowspan=3, padx=10, pady=8)

        self.lbl_title = ctk.CTkLabel(
            self, text=filename, anchor="w", font=("Segoe UI", 12, "bold")
        )
        self.lbl_title.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(6, 0))

        self.lbl_status = ctk.CTkLabel(
            self,
            text=f"Convertendo para {target_format.upper()}...",
            anchor="w",
            text_color=self.color,
            font=("Segoe UI", 11),
        )
        self.lbl_status.grid(row=1, column=1, sticky="ew", padx=(0, 10))

        self.progress = ctk.CTkProgressBar(self, height=8)
        self.progress.configure(progress_color=self.color)
        self.progress.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=(5, 10))
        self.progress.set(0.05)

        threading.Thread(target=self._convert, daemon=True).start()

    def _update_conv_ui(self, pct, status_text, color=None, output_file=None):
        def _apply():
            if not self.winfo_exists():
                return
            self.progress.set(max(0.0, min(1.0, float(pct))))
            self.lbl_status.configure(text=status_text)
            if color:
                self.lbl_status.configure(text_color=color)
            if output_file:
                btn_open = ctk.CTkButton(
                    self,
                    text="📂",
                    width=32,
                    height=32,
                    fg_color="#2B2B2B",
                    hover_color="#444444",
                    command=lambda: subprocess.run(
                        ["explorer", "/select,", os.path.normpath(output_file)]
                    ),
                )
                btn_open.grid(row=0, column=2, rowspan=3, padx=10)

        self.after(0, _apply)

    def _convert(self):
        try:
            if self.ffmpeg_ready_event and not self.ffmpeg_ready_event.is_set():
                self._update_conv_ui(
                    0.02,
                    "⏳ Na fila (Aguardando download do FFmpeg concluir)...",
                    color="#FBBF24",
                )
                self.ffmpeg_ready_event.wait()

            filename = os.path.splitext(os.path.basename(self.filepath))[0]
            output_file = os.path.join(self.output_folder, f"{filename}.{self.target_format}")
            count = 1
            base = output_file
            while os.path.exists(output_file):
                output_file = f"{os.path.splitext(base)[0]} ({count}).{self.target_format}"
                count += 1

            ffmpeg = self.tools.get("ffmpeg")
            while not ffmpeg or not os.path.exists(ffmpeg):
                self._update_conv_ui(
                    0.02,
                    "⏳ Na fila (Aguardando FFmpeg)...",
                    color="#FBBF24",
                )
                sleep(0.5)
                ffmpeg = self.tools.get("ffmpeg")

            cmd = [ffmpeg, "-y", "-i", self.filepath]
            if self.target_format == "mp4":
                cmd.extend(
                    ["-c:v", "libx264", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", output_file]
                )
            elif self.target_format == "mp3":
                cmd.extend(["-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k", output_file])
            elif self.target_format == "wav":
                cmd.extend(["-vn", "-ar", "44100", "-ac", "2", output_file])
            else:
                cmd.append(output_file)

            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )

            total_duration = None
            for line in proc.stdout:
                if total_duration is None:
                    m_dur = re.search(r"Duration:\s*(\d+:\d+:\d+\.\d+)", line)
                    if m_dur:
                        try:
                            total_duration = tempo_para_segundos(m_dur.group(1))
                        except Exception:
                            pass
                else:
                    m_time = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                    if m_time and total_duration > 0:
                        try:
                            cur = tempo_para_segundos(m_time.group(1))
                            pct = min(0.99, cur / total_duration)
                            self._update_conv_ui(
                                pct,
                                f"Convertendo para {self.target_format.upper()}: {pct*100:.0f}%",
                            )
                        except Exception:
                            pass

            proc.wait()
            if proc.returncode == 0 and os.path.exists(output_file):
                self._update_conv_ui(
                    1.0,
                    f"Conversão para {self.target_format.upper()} Concluída!",
                    color="#2CC985",
                    output_file=output_file,
                )
            else:
                raise RuntimeError("Falha ao converter arquivo com FFmpeg.")
        except Exception as e:
            self._update_conv_ui(0.0, f"Erro: {e}", color="#EF4444")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Youtube Downloader Ultimate - Igreja & Mídia")
        self.geometry("980x720")
        self.minsize(860, 620)
        try:
            self.iconbitmap(resource_path("app_icon.ico"))
        except Exception:
            pass

        # Diretórios de configuração e binários
        self.app_data_dir = os.path.join(os.path.expanduser("~"), ".yt_downloader_pro")
        os.makedirs(self.app_data_dir, exist_ok=True)
        self.bin_dir = os.path.join(self.app_data_dir, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        self.history_file = os.path.join(self.app_data_dir, "history.json")
        self.settings_file = os.path.join(self.app_data_dir, "settings.json")

        self.settings = self._load_settings()
        self.download_folder = self.settings.get(
            "download_folder", os.path.join(os.path.expanduser("~"), "Downloads")
        )
        self.cookie_file = self.settings.get("cookie_file", None)

        # Eventos de sincronização para permitir enfileiramento imediato enquanto baixa ferramentas
        self.ytdlp_ready_event = threading.Event()
        self.ffmpeg_ready_event = threading.Event()

        yt_init = os.path.join(self.bin_dir, "yt-dlp.exe")
        ff_init = os.path.join(self.bin_dir, "ffmpeg.exe")
        sys_yt_init = shutil.which("yt-dlp")
        sys_ff_init = shutil.which("ffmpeg")

        self.tools = {
            "yt-dlp": yt_init if os.path.exists(yt_init) else sys_yt_init,
            "ffmpeg": ff_init if os.path.exists(ff_init) else sys_ff_init,
        }
        if self.tools["yt-dlp"]:
            self.ytdlp_ready_event.set()
        if self.tools["ffmpeg"]:
            self.ffmpeg_ready_event.set()

        self.history_data = self._load_history()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Abas Principais
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=12, pady=(8, 4))
        self.tab_down = self.tabview.add("⬇ DOWNLOADER")
        self.tab_conv = self.tabview.add("🔄 CONVERSOR")
        self.tab_hist = self.tabview.add("📜 HISTÓRICO")

        self.setup_downloader_tab()
        self.setup_converter_tab()
        self.setup_history_tab()

        # Rodapé: Configurações de Pasta, Cookies Automáticos e Barra de Status de Ferramentas
        self.setup_footer()

        # Verifica e baixa yt-dlp / FFmpeg em segundo plano com progresso na barra de status
        self.after(
            150,
            lambda: threading.Thread(
                target=self.manage_tools, args=(False,), daemon=True
            ).start(),
        )

    # --- PERSISTÊNCIA (CONFIGURAÇÕES E HISTÓRICO) ---
    def _load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "download_folder": self.download_folder,
                        "cookie_file": self.cookie_file,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass

    def _load_history(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
        except Exception:
            pass
        return []

    def _add_to_history(self, entry):
        self.history_data.insert(0, entry)
        self.history_data = self.history_data[:100]  # Mantém últimos 100
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        self.refresh_history_ui()

    # --- INTERFACE: ABA DOWNLOADER ---
    def setup_downloader_tab(self):
        self.tab_down.grid_columnconfigure(0, weight=1)
        self.tab_down.grid_rowconfigure(3, weight=1)

        # Linha 0: Entrada de Link + Botão Colar
        self.frame_top = ctk.CTkFrame(self.tab_down)
        self.frame_top.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 6))
        self.frame_top.grid_columnconfigure(0, weight=1)

        self.entry_link = ctk.CTkEntry(
            self.frame_top,
            placeholder_text="Cole o link do YouTube, Instagram, TikTok, Facebook, X ou Playlist aqui...",
            height=38,
            font=("Segoe UI", 13),
        )
        self.entry_link.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.entry_link.bind("<Return>", lambda e: self.preparar_download())

        self.btn_paste = ctk.CTkButton(
            self.frame_top,
            text="📋 Colar",
            width=90,
            height=38,
            fg_color="#3A3A3A",
            hover_color="#505050",
            command=self.colar_link,
        )
        self.btn_paste.grid(row=0, column=1, padx=(0, 10))

        # Linha 1: Opções Principais (Modo, Qualidade, Escopo Playlist, Legendas, Botão Baixar)
        self.frame_opts = ctk.CTkFrame(self.tab_down, fg_color="transparent")
        self.frame_opts.grid(row=1, column=0, sticky="ew", padx=10, pady=4)

        self.mode_switch = ctk.CTkSegmentedButton(
            self.frame_opts,
            values=["VÍDEO (MP4)", "ÁUDIO (MP3)"],
            width=210,
            command=self.toggle_quality,
        )
        self.mode_switch.set("VÍDEO (MP4)")
        self.mode_switch.pack(side="left", padx=(0, 8))

        self.quality_menu = ctk.CTkOptionMenu(
            self.frame_opts,
            values=["4K (Máxima)", "1080p (Full HD)", "720p (HD)", "480p (Leve)"],
            width=145,
        )
        self.quality_menu.set("1080p (Full HD)")
        self.quality_menu.pack(side="left", padx=5)

        self.playlist_scope = ctk.CTkOptionMenu(
            self.frame_opts,
            values=["Vídeo Único", "Playlist Completa"],
            width=150,
            fg_color="#2B2B2B",
            button_color="#3B3B3B",
        )
        self.playlist_scope.set("Vídeo Único")
        self.playlist_scope.pack(side="left", padx=5)

        self.check_subs = ctk.CTkCheckBox(self.frame_opts, text="Legendas", width=80)
        self.check_subs.pack(side="left", padx=8)

        self.btn_download = ctk.CTkButton(
            self.frame_opts,
            text="＋ ADICIONAR À FILA",
            width=165,
            height=36,
            font=("Segoe UI", 12, "bold"),
            fg_color="#2CC985",
            text_color="#051b11",
            hover_color="#229e68",
            command=self.preparar_download,
        )
        self.btn_download.pack(side="right", padx=5)

        # Linha 2: Barra de Recorte de Trecho (Trim) e Autenticação/Cookies
        self.frame_adv = ctk.CTkFrame(self.tab_down, fg_color="#1E1E1E", corner_radius=8)
        self.frame_adv.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 6))

        self.check_trim = ctk.CTkCheckBox(
            self.frame_adv,
            text="✂️ Recortar Trecho:",
            command=self.toggle_trim_inputs,
            font=("Segoe UI", 12),
        )
        self.check_trim.pack(side="left", padx=(12, 6), pady=8)

        self.entry_trim_start = ctk.CTkEntry(
            self.frame_adv,
            placeholder_text="Início (00:01:00)",
            width=115,
            height=28,
            state="disabled",
        )
        self.entry_trim_start.pack(side="left", padx=4, pady=8)

        ctk.CTkLabel(self.frame_adv, text="até", text_color="gray").pack(
            side="left", padx=2
        )

        self.entry_trim_end = ctk.CTkEntry(
            self.frame_adv,
            placeholder_text="Fim (00:02:30)",
            width=115,
            height=28,
            state="disabled",
        )
        self.entry_trim_end.pack(side="left", padx=4, pady=8)

        # Seletor de Cookies / Login Automático do Navegador
        self.btn_cookie_file = ctk.CTkButton(
            self.frame_adv,
            text="Selecionar .txt",
            width=100,
            height=28,
            fg_color="#333333",
            command=self.sel_cookies,
        )

        self.auth_menu = ctk.CTkOptionMenu(
            self.frame_adv,
            values=[
                "Sem Cookies (Público)",
                "Chrome (Automático)",
                "Edge (Automático)",
                "Firefox (Automático)",
                "Brave (Automático)",
                "Opera (Automático)",
                "Arquivo .txt Manual",
            ],
            width=175,
            height=28,
            fg_color="#2B2B2B",
            button_color="#3B3B3B",
            command=self.on_auth_change,
        )
        self.auth_menu.set("Sem Cookies (Público)")
        self.auth_menu.pack(side="right", padx=10, pady=8)

        ctk.CTkLabel(
            self.frame_adv,
            text="🔑 Login / Cookies:",
            font=("Segoe UI", 12),
            text_color="gray80",
        ).pack(side="right", padx=(10, 4))

        # Linha 3: Fila de Downloads
        self.scroll_down = ctk.CTkScrollableFrame(
            self.tab_down, label_text="Fila de Downloads Ativos e Concluídos"
        )
        self.scroll_down.grid(row=3, column=0, sticky="nsew", padx=10, pady=4)

    # --- INTERFACE: ABA CONVERSOR ---
    def setup_converter_tab(self):
        self.tab_conv.grid_columnconfigure(0, weight=1)
        self.tab_conv.grid_rowconfigure(2, weight=1)

        self.lbl_conv = ctk.CTkLabel(
            self.tab_conv,
            text="Converta arquivos locais de Vídeo ou Áudio usando o FFmpeg integrado",
            font=("Segoe UI", 14, "bold"),
        )
        self.lbl_conv.grid(row=0, column=0, pady=(15, 8))

        self.frame_conv_btns = ctk.CTkFrame(self.tab_conv, fg_color="transparent")
        self.frame_conv_btns.grid(row=1, column=0, pady=6)

        self.btn_add_vid = ctk.CTkButton(
            self.frame_conv_btns,
            text="🎬 Converter para MP4 (H.264)",
            width=210,
            height=40,
            fg_color="#2CC985",
            text_color="#051b11",
            hover_color="#229e68",
            font=("Segoe UI", 12, "bold"),
            command=lambda: self.add_conversion("mp4"),
        )
        self.btn_add_vid.pack(side="left", padx=8)

        self.btn_add_aud = ctk.CTkButton(
            self.frame_conv_btns,
            text="🎵 Extrair Áudio MP3 (192kbps)",
            width=210,
            height=40,
            fg_color="#3B8ED0",
            hover_color="#2c6fa3",
            font=("Segoe UI", 12, "bold"),
            command=lambda: self.add_conversion("mp3"),
        )
        self.btn_add_aud.pack(side="left", padx=8)

        self.btn_add_wav = ctk.CTkButton(
            self.frame_conv_btns,
            text="🎙️ Extrair Áudio WAV (Sem Perda)",
            width=220,
            height=40,
            fg_color="#8B5CF6",
            hover_color="#6D28D9",
            font=("Segoe UI", 12, "bold"),
            command=lambda: self.add_conversion("wav"),
        )
        self.btn_add_wav.pack(side="left", padx=8)

        self.scroll_conv = ctk.CTkScrollableFrame(
            self.tab_conv, label_text="Fila de Conversão de Arquivos"
        )
        self.scroll_conv.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)

    # --- INTERFACE: ABA HISTÓRICO ---
    def setup_history_tab(self):
        self.tab_hist.grid_columnconfigure(0, weight=1)
        self.tab_hist.grid_rowconfigure(1, weight=1)

        top_hist = ctk.CTkFrame(self.tab_hist, fg_color="transparent")
        top_hist.grid(row=0, column=0, sticky="ew", padx=10, pady=6)

        ctk.CTkLabel(
            top_hist,
            text="Histórico de Downloads Recentes",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            top_hist,
            text="🗑️ Limpar Histórico",
            width=140,
            height=30,
            fg_color="#442222",
            hover_color="#662222",
            command=self.clear_history,
        ).pack(side="right", padx=5)

        self.scroll_hist = ctk.CTkScrollableFrame(self.tab_hist)
        self.scroll_hist.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        self.refresh_history_ui()

    def refresh_history_ui(self):
        for widget in self.scroll_hist.winfo_children():
            widget.destroy()

        if not self.history_data:
            ctk.CTkLabel(
                self.scroll_hist,
                text="Nenhum download registrado no histórico ainda.",
                text_color="gray",
            ).pack(pady=30)
            return

        for item in self.history_data:
            row = ctk.CTkFrame(self.scroll_hist, fg_color="#222222", corner_radius=6)
            row.pack(fill="x", padx=5, pady=4)
            row.grid_columnconfigure(0, weight=1)

            title = item.get("title", "Sem título")
            meta = f"{item.get('date', '')}  •  {item.get('quality', '')}"
            path = item.get("path", "")
            url = item.get("url", "")

            ctk.CTkLabel(
                row,
                text=title[:75] + ("..." if len(title) > 75 else ""),
                anchor="w",
                font=("Segoe UI", 12, "bold"),
            ).grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))

            ctk.CTkLabel(
                row,
                text=f"{meta}  •  {path}",
                anchor="w",
                font=("Segoe UI", 10),
                text_color="gray",
            ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.grid(row=0, column=1, rowspan=2, padx=8)

            if path and os.path.exists(path):
                ctk.CTkButton(
                    btns,
                    text="▶",
                    width=30,
                    height=28,
                    fg_color="#2CC985",
                    text_color="#051b11",
                    command=lambda p=path: os.startfile(p)
                    if sys.platform == "win32"
                    else None,
                ).pack(side="left", padx=2)
                ctk.CTkButton(
                    btns,
                    text="📂",
                    width=30,
                    height=28,
                    fg_color="#333333",
                    command=lambda p=path: subprocess.run(
                        ["explorer", "/select,", os.path.normpath(p)]
                    ),
                ).pack(side="left", padx=2)

            if url:
                ctk.CTkButton(
                    btns,
                    text="🔄 Baixar Novamente",
                    width=130,
                    height=28,
                    fg_color="#2B2B2B",
                    command=lambda u=url: self.requeue_from_history(u),
                ).pack(side="left", padx=4)

    def requeue_from_history(self, url):
        self.tabview.set("⬇ DOWNLOADER")
        self.entry_link.delete(0, "end")
        self.entry_link.insert(0, url)
        self.preparar_download()

    def clear_history(self):
        self.history_data = []
        try:
            if os.path.exists(self.history_file):
                os.remove(self.history_file)
        except Exception:
            pass
        self.refresh_history_ui()

    # --- RODAPÉ E BARRA DE STATUS DE INSTALAÇÃO ---
    def setup_footer(self):
        self.frame_bot = ctk.CTkFrame(self, fg_color="#1A1A1A", corner_radius=8)
        self.frame_bot.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 10))
        self.frame_bot.grid_columnconfigure(1, weight=1)

        self.btn_folder = ctk.CTkButton(
            self.frame_bot,
            text="📁 Alterar Pasta",
            width=120,
            height=30,
            fg_color="#2B2B2B",
            hover_color="#3F3F3F",
            command=self.sel_folder,
        )
        self.btn_folder.grid(row=0, column=0, padx=8, pady=8)

        self.lbl_folder = ctk.CTkLabel(
            self.frame_bot,
            text=f"Salvar em: {self.download_folder}",
            text_color="gray80",
            anchor="w",
            font=("Segoe UI", 11),
        )
        self.lbl_folder.grid(row=0, column=1, sticky="ew", padx=6)

        # Status das ferramentas (yt-dlp + FFmpeg)
        self.lbl_tools_status = ctk.CTkLabel(
            self.frame_bot,
            text="⏳ Verificando yt-dlp e FFmpeg...",
            text_color="#FBBF24",
            font=("Segoe UI", 11, "bold"),
        )
        self.lbl_tools_status.grid(row=0, column=2, padx=10)

        self.tools_progress = ctk.CTkProgressBar(self.frame_bot, width=110, height=8)
        self.tools_progress.grid(row=0, column=3, padx=(0, 10))
        self.tools_progress.set(0)

        self.btn_update = ctk.CTkButton(
            self.frame_bot,
            text="🔄 Atualizar Motor",
            width=135,
            height=30,
            fg_color="#2B2B2B",
            hover_color="#3F3F3F",
            command=self.start_update,
        )
        self.btn_update.grid(row=0, column=4, padx=8, pady=8)

    # --- EVENTOS E HELPERS DA UI ---
    def toggle_quality(self, choice):
        state = "disabled" if "ÁUDIO" in choice else "normal"
        self.quality_menu.configure(state=state)
        self.check_subs.configure(state=state)

    def toggle_trim_inputs(self):
        state = "normal" if self.check_trim.get() else "disabled"
        self.entry_trim_start.configure(state=state)
        self.entry_trim_end.configure(state=state)

    def on_auth_change(self, choice):
        if "Arquivo .txt" in choice:
            self.btn_cookie_file.pack(side="right", padx=4, pady=8)
            if not self.cookie_file:
                self.sel_cookies()
        else:
            self.btn_cookie_file.pack_forget()

    def _get_current_auth_config(self):
        choice = self.auth_menu.get()
        if "Chrome" in choice:
            return {"type": "browser", "value": "chrome"}
        elif "Edge" in choice:
            return {"type": "browser", "value": "edge"}
        elif "Firefox" in choice:
            return {"type": "browser", "value": "firefox"}
        elif "Brave" in choice:
            return {"type": "browser", "value": "brave"}
        elif "Opera" in choice:
            return {"type": "browser", "value": "opera"}
        elif "Arquivo .txt" in choice and self.cookie_file:
            return {"type": "file", "value": self.cookie_file}
        return {"type": "none", "value": None}

    def colar_link(self):
        try:
            texto = self.clipboard_get().strip()
            self.entry_link.delete(0, "end")
            self.entry_link.insert(0, texto)
        except Exception:
            pass

    def sel_folder(self):
        d = filedialog.askdirectory(initialdir=self.download_folder)
        if d:
            self.download_folder = d
            self.lbl_folder.configure(text=f"Salvar em: {d}")
            self._save_settings()

    def sel_cookies(self):
        f = filedialog.askopenfilename(filetypes=[("Cookies Netscape TXT", "*.txt")])
        if f:
            self.cookie_file = f
            self.btn_cookie_file.configure(
                fg_color="#2CC985", text_color="#051b11", text="Cookies OK"
            )
            self._save_settings()

    def add_conversion(self, target_format):
        filetypes = (
            [("Vídeos", "*.mp4;*.mkv;*.avi;*.mov;*.webm;*.flv;*.ts")]
            if target_format == "mp4"
            else [("Mídia de Áudio/Vídeo", "*.mp4;*.mkv;*.webm;*.mp3;*.wav;*.m4a;*.ogg;*.flac")]
        )
        files = filedialog.askopenfilenames(filetypes=filetypes)
        for f in files:
            ConverterItem(
                self.scroll_conv,
                f,
                self.download_folder,
                self.tools,
                target_format,
                ffmpeg_ready_event=self.ffmpeg_ready_event,
            ).pack(fill="x", padx=5, pady=5)

    # --- GERENCIAMENTO E ATUALIZAÇÃO DE FERRAMENTAS (yt-dlp + FFmpeg) ---
    def _set_tools_status(self, text, pct=None, color="#FBBF24", btn_state="normal"):
        def _apply():
            self.lbl_tools_status.configure(text=text, text_color=color)
            if pct is not None:
                self.tools_progress.set(max(0.0, min(1.0, float(pct))))
            self.btn_update.configure(state=btn_state)

        self.after(0, _apply)

    def start_update(self):
        self._set_tools_status(
            "⏳ Buscando atualizações...", pct=0.1, color="#FBBF24", btn_state="disabled"
        )
        threading.Thread(target=self.manage_tools, args=(True,), daemon=True).start()

    def _download_with_progress(self, url, dest_path, label_prefix):
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded / total
                        self._set_tools_status(
                            f"⬇ {label_prefix}: {pct*100:.0f}%",
                            pct=pct,
                            color="#3B8ED0",
                            btn_state="disabled",
                        )

    def manage_tools(self, force=False):
        yt = os.path.join(self.bin_dir, "yt-dlp.exe")
        ff = os.path.join(self.bin_dir, "ffmpeg.exe")

        # Fallback: verifica se yt-dlp ou ffmpeg já existem no PATH do sistema
        sys_yt = shutil.which("yt-dlp")
        sys_ff = shutil.which("ffmpeg")

        try:
            if not os.path.exists(yt) or force:
                if force and os.path.exists(yt):
                    # Tenta atualizar via próprio yt-dlp -U primeiro (muito mais rápido)
                    creation_flags = (
                        subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    )
                    self._set_tools_status(
                        "🔄 Atualizando yt-dlp...",
                        pct=0.4,
                        color="#3B8ED0",
                        btn_state="disabled",
                    )
                    subprocess.run(
                        [yt, "-U"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=creation_flags,
                    )
                else:
                    self._download_with_progress(
                        "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
                        yt,
                        "Baixando yt-dlp",
                    )

            # Assim que o yt-dlp estiver disponível, já libera a leitura de metadados/capas na fila!
            self.tools["yt-dlp"] = yt if os.path.exists(yt) else sys_yt
            if self.tools["yt-dlp"]:
                self.ytdlp_ready_event.set()

            if not os.path.exists(ff):
                if sys_ff and not force:
                    ff = sys_ff
                else:
                    temp_zip = os.path.join(self.app_data_dir, "ffmpeg_temp.zip")
                    self._download_with_progress(
                        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
                        temp_zip,
                        "Baixando FFmpeg",
                    )
                    self._set_tools_status(
                        "📦 Extraindo FFmpeg...",
                        pct=0.9,
                        color="#FBBF24",
                        btn_state="disabled",
                    )
                    with zipfile.ZipFile(temp_zip) as z:
                        for m in z.infolist():
                            if m.filename.endswith("ffmpeg.exe"):
                                m.filename = "ffmpeg.exe"
                                z.extract(m, self.bin_dir)
                            elif m.filename.endswith("ffprobe.exe"):
                                m.filename = "ffprobe.exe"
                                z.extract(m, self.bin_dir)
                    if os.path.exists(temp_zip):
                        os.remove(temp_zip)

            self.tools = {
                "yt-dlp": yt if os.path.exists(yt) else sys_yt,
                "ffmpeg": ff if os.path.exists(ff) else sys_ff,
            }
            if self.tools["yt-dlp"]:
                self.ytdlp_ready_event.set()
            self.ffmpeg_ready_event.set()

            if self.tools["yt-dlp"] and self.tools["ffmpeg"]:
                self._set_tools_status(
                    "✅ Motor Pronto (yt-dlp + FFmpeg)",
                    pct=1.0,
                    color="#2CC985",
                    btn_state="normal",
                )
            elif self.tools["yt-dlp"]:
                self._set_tools_status(
                    "⚠️ yt-dlp Pronto (Sem FFmpeg)",
                    pct=0.7,
                    color="#FBBF24",
                    btn_state="normal",
                )
            else:
                self._set_tools_status(
                    "❌ Erro ao baixar componentes",
                    pct=0.0,
                    color="#EF4444",
                    btn_state="normal",
                )
        except Exception as e:
            self.tools = {
                "yt-dlp": yt if os.path.exists(yt) else sys_yt,
                "ffmpeg": ff if os.path.exists(ff) else sys_ff,
            }
            if self.tools["yt-dlp"]:
                self.ytdlp_ready_event.set()
            self.ffmpeg_ready_event.set()
            self._set_tools_status(
                f"⚠️ Erro na atualização: {str(e)[:30]}",
                pct=0.0,
                color="#EF4444",
                btn_state="normal",
            )

    # --- PREPARAÇÃO DO DOWNLOAD (VÍDEO ÚNICO OU PLAYLIST COMPLETA) ---
    def preparar_download(self):
        url = self.entry_link.get().strip()
        if not url:
            return

        # Valida recorte de tempo se ativado
        trim_range = None
        if self.check_trim.get():
            try:
                ini = validar_tempo_corte(self.entry_trim_start.get())
                fim = validar_tempo_corte(self.entry_trim_end.get())
                if not ini and not fim:
                    return messagebox.showwarning(
                        "Recorte de Trecho",
                        "Informe pelo menos o tempo inicial ou final (ex: 00:01:00).",
                    )
                trim_range = (ini, fim)
            except ValueError as err:
                return messagebox.showerror("Tempo Inválido", str(err))

        mode_text = self.mode_switch.get()
        mode = "audio" if "ÁUDIO" in mode_text else "video"
        quality = self.quality_menu.get()
        subs = bool(self.check_subs.get())
        auth_config = self._get_current_auth_config()
        is_playlist = self.playlist_scope.get() == "Playlist Completa"

        self.entry_link.delete(0, "end")

        if is_playlist and ("list=" in url or "/playlist" in url):
            threading.Thread(
                target=self._expandir_playlist,
                args=(url, mode, quality, subs, auth_config, trim_range),
                daemon=True,
            ).start()
        else:
            self._adicionar_item_fila(
                url, mode, quality, subs, auth_config, trim_range, prefetched_info=None
            )

    def _adicionar_item_fila(
        self, url, mode, quality, subs, auth_config, trim_range, prefetched_info=None
    ):
        def _add():
            item = DownloadItem(
                self.scroll_down,
                url,
                self.download_folder,
                self.tools,
                mode,
                quality,
                subs,
                auth_config=auth_config,
                trim_range=trim_range,
                prefetched_info=prefetched_info,
                on_complete_callback=self._add_to_history,
                ytdlp_ready_event=self.ytdlp_ready_event,
                ffmpeg_ready_event=self.ffmpeg_ready_event,
            )
            item.pack(fill="x", padx=5, pady=5)
            item.start()

        self.after(0, _add)

    def _expandir_playlist(self, url, mode, quality, subs, auth_config, trim_range):
        """Busca os vídeos de uma playlist com --flat-playlist e adiciona cada um na fila."""
        try:
            if not self.ytdlp_ready_event.is_set():
                self.ytdlp_ready_event.wait()

            self._set_tools_status(
                "📋 Carregando vídeos da Playlist...", pct=0.5, color="#3B8ED0"
            )
            yt_dlp_bin = self.tools["yt-dlp"]
            cmd = [
                yt_dlp_bin,
                "--flat-playlist",
                "--dump-single-json",
                "--no-warnings",
                url,
            ]
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
            if res.returncode != 0:
                raise RuntimeError("Não foi possível ler a playlist.")

            data = json.loads(res.stdout.strip().splitlines()[-1])
            entries = data.get("entries") or []
            if not entries:
                # Não era playlist ou tinha 1 vídeo só
                self._adicionar_item_fila(url, mode, quality, subs, auth_config, trim_range)
                self._set_tools_status(
                    "✅ Motor Pronto (yt-dlp + FFmpeg)", pct=1.0, color="#2CC985"
                )
                return

            count = 0
            for entry in entries:
                vid_url = entry.get("url") or entry.get("webpage_url")
                vid_id = entry.get("id")
                if not vid_url and vid_id:
                    vid_url = f"https://www.youtube.com/watch?v={vid_id}"
                if not vid_url:
                    continue
                thumbs = entry.get("thumbnails") or []
                thumb_url = thumbs[-1].get("url") if thumbs else None
                prefetched = {
                    "title": entry.get("title") or vid_url,
                    "thumbnail": thumb_url,
                }
                self._adicionar_item_fila(
                    vid_url, mode, quality, subs, auth_config, trim_range, prefetched
                )
                count += 1

            self._set_tools_status(
                f"✅ {count} vídeos da playlist adicionados!", pct=1.0, color="#2CC985"
            )
        except Exception:
            self._adicionar_item_fila(url, mode, quality, subs, auth_config, trim_range)
            self._set_tools_status(
                "✅ Motor Pronto (yt-dlp + FFmpeg)", pct=1.0, color="#2CC985"
            )


if __name__ == "__main__":
    App().mainloop()
