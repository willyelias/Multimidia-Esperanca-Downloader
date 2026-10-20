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
from urllib.parse import urlencode
import tkinter as tk
from tkinter import filedialog, messagebox

import requests
import zipfile
import customtkinter as ctk
from PIL import Image
from plyer import notification


# --- FUNÇÃO PARA RECURSOS EMBUTIDOS NO .EXE (PyInstaller) ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    candidate = os.path.join(base_path, relative_path)
    if os.path.exists(candidate):
        return candidate
    # Fallback para pasta desktop/ ou web/
    for sub in ("desktop", "web"):
        alt = os.path.join(base_path, sub, relative_path)
        if os.path.exists(alt):
            return alt
    return candidate


def validar_tempo_corte(valor: str) -> str:
    """Valida e normaliza uma string de tempo (ex: '1:30', '00:01:30', '90')."""
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


# --- PALETA DE CORES IDÊNTICA À VERSÃO ONLINE (WEB STUDIO) ---
BG_DARK = "#0a0c10"
BG_CARD = "#161a22"
BG_ELEVATED = "#1c222d"
BG_INPUT = "#131720"
BG_SUBROW = "#0d1017"
BORDER_COLOR = "#262d3d"
BORDER_ACTIVE = "#2cc985"
TEXT_MAIN = "#f8fafc"
TEXT_MUTED = "#94a3b8"
GREEN_BRIGHT = "#2cc985"
GREEN_HOVER = "#10b981"
GREEN_DARK_TEXT = "#041f14"
BLUE_AUDIO = "#3b82f6"
BLUE_HOVER = "#2563eb"
DANGER_COLOR = "#ef4444"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")


class DownloadItem(ctk.CTkFrame):
    """Card individual da fila de downloads com o mesmo design e funções da versão Web."""

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
        on_remove_callback=None,
        ytdlp_ready_event=None,
        ffmpeg_ready_event=None,
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color=BG_ELEVATED,
            corner_radius=12,
            border_width=1,
            border_color=BORDER_COLOR,
            **kwargs,
        )
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
        self.on_remove_callback = on_remove_callback
        self.ytdlp_ready_event = ytdlp_ready_event
        self.ffmpeg_ready_event = ffmpeg_ready_event

        self.processo = None
        self.is_cancelled = False
        self.is_done = False
        self.final_absolute_path = None
        self.title_text = (
            prefetched_info.get("title", url) if prefetched_info else url
        )

        self.grid_columnconfigure(1, weight=1)

        if mode == "audio":
            icon_mode = "🎵"
            self.color_mode = BLUE_AUDIO
        else:
            icon_mode = "🎬"
            self.color_mode = GREEN_BRIGHT

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

        # 1. Capa (Thumbnail 124x70 como na Web)
        self.lbl_thumb = ctk.CTkLabel(
            self,
            text="⏳",
            width=124,
            height=70,
            fg_color="#10131a",
            corner_radius=8,
            font=("Segoe UI", 20),
        )
        self.lbl_thumb.grid(row=0, column=0, rowspan=3, padx=14, pady=12)

        # 2. Informações de Status e Título
        self.lbl_info = ctk.CTkLabel(
            self,
            text=f"{self.info_prefix} Obtendo informações do vídeo...",
            anchor="w",
            font=("Segoe UI", 12, "bold"),
            text_color=TEXT_MUTED,
        )
        self.lbl_info.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 0))

        initial_title = (
            self.title_text[:72] + "..."
            if len(self.title_text) > 72
            else self.title_text
        )
        self.lbl_title = ctk.CTkLabel(
            self,
            text=initial_title,
            anchor="w",
            font=("Segoe UI", 14, "bold"),
            text_color=TEXT_MAIN,
        )
        self.lbl_title.grid(row=1, column=1, sticky="ew", padx=(0, 12))

        # 3. Barra de Progresso
        self.progress = ctk.CTkProgressBar(
            self, height=9, corner_radius=99, fg_color="#0f131a"
        )
        self.progress.configure(progress_color=self.color_mode)
        self.progress.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=(6, 12))
        self.progress.set(0.06)

        # 4. Ações (Visualizar, Salvar/Abrir Pasta, Remover)
        self.frame_btns = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_btns.grid(row=0, column=2, rowspan=3, padx=14)

        self.btn_cancel = ctk.CTkButton(
            self.frame_btns,
            text="✕",
            width=34,
            height=34,
            corner_radius=8,
            fg_color="transparent",
            text_color=TEXT_MUTED,
            hover_color="#382020",
            command=self.cancelar_download,
        )
        self.btn_cancel.pack(side="right", padx=2)

        self.btn_play = ctk.CTkButton(
            self.frame_btns,
            text="▶ Visualizar",
            width=105,
            height=34,
            corner_radius=8,
            font=("Segoe UI", 12, "bold"),
            fg_color="#283040",
            text_color=TEXT_MAIN,
            hover_color="#364156",
            command=self.reproduzir_arquivo,
        )
        self.btn_folder = ctk.CTkButton(
            self.frame_btns,
            text="📂 Abrir Pasta",
            width=115,
            height=34,
            corner_radius=8,
            font=("Segoe UI", 12, "bold"),
            fg_color=self.color_mode,
            text_color=GREEN_DARK_TEXT if mode != "audio" else "#ffffff",
            hover_color=GREEN_HOVER if mode != "audio" else BLUE_HOVER,
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
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(124, 70))
                if not self.is_cancelled:
                    self.after(
                        0, lambda: self.lbl_thumb.configure(image=ctk_img, text="")
                    )
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
        if self.on_remove_callback:
            self.on_remove_callback()

    def reproduzir_arquivo(self):
        if self.final_absolute_path and os.path.exists(self.final_absolute_path):
            try:
                if sys.platform == "win32":
                    os.startfile(self.final_absolute_path)
                else:
                    subprocess.run(["xdg-open", self.final_absolute_path])
            except Exception as e:
                messagebox.showerror("Erro Player", f"Não foi possível abrir:\n{e}")
        else:
            messagebox.showerror("Erro", "Arquivo não encontrado no disco.")

    def abrir_local_arquivo(self):
        if sys.platform == "win32":
            try:
                if self.final_absolute_path and os.path.exists(self.final_absolute_path):
                    subprocess.run(
                        [
                            "explorer",
                            "/select,",
                            os.path.normpath(self.final_absolute_path),
                        ]
                    )
                else:
                    os.startfile(self.folder)
            except Exception:
                os.startfile(self.folder)

    def start(self):
        threading.Thread(target=self._logic_completa, daemon=True).start()

    def _update_ui(
        self,
        percent,
        status_text,
        finished=False,
        final_path=None,
        title=None,
        color=None,
    ):
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
                display_title = title[:72] + "..." if len(title) > 72 else title
                self.lbl_title.configure(text=display_title)

            if final_path:
                self.final_absolute_path = final_path

            if finished:
                self.is_done = True
                self.configure(border_color=GREEN_BRIGHT)
                self.btn_folder.pack(side="right", padx=4)
                self.btn_play.pack(side="right", padx=4)
                try:
                    notification.notify(
                        title="Download Concluído!",
                        message=f"{self.title_text[:80]}",
                        app_name="Multimídia Esperança Downloader",
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
                            "quality": "MP3 Áudio"
                            if self.mode == "audio"
                            else self.quality,
                            "path": self.final_absolute_path,
                            "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        }
                    )

        self.after(0, _apply)

    def gerar_nome_unico(self, base_filename):
        nome, ext = os.path.splitext(base_filename)
        contador = 1
        novo_nome = base_filename
        while os.path.exists(os.path.join(self.folder, novo_nome)):
            novo_nome = f"{nome} ({contador}){ext}"
            contador += 1
        return novo_nome

    def _get_auth_args(self):
        auth_type = self.auth_config.get("type", "none")
        auth_val = self.auth_config.get("value")
        if auth_type == "browser" and auth_val:
            return ["--cookies-from-browser", auth_val]
        elif auth_type == "file" and auth_val and os.path.exists(auth_val):
            return ["--cookies", auth_val]
        return []

    def _try_cloud_direct_download(self, clean_url, ext_final):
        """
        Motor Online Direto (idêntico à versão Web do Netlify):
        Permite baixar vídeos/MP3 imediatamente mesmo se o FFmpeg local ainda estiver instalando
        ou como fallback automático caso o yt-dlp local encontre bloqueio sem cookies!
        """
        fmt = "mp3" if self.mode == "audio" else "1080"
        if self.mode != "audio":
            if "4K" in self.quality:
                fmt = "4k"
            elif "720p" in self.quality:
                fmt = "720"
            elif "480p" in self.quality:
                fmt = "480"

        params = {"button": "1", "format": fmt, "url": clean_url}
        if self.trim_range and self.trim_range[0]:
            params["start_time"] = self.trim_range[0]
        if self.trim_range and self.trim_range[1]:
            params["end_time"] = self.trim_range[1]

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        init_data = None
        for domain in ("p.savenow.to", "p.lbserver.xyz"):
            try:
                r = requests.get(
                    f"https://{domain}/api/v2/download?{urlencode(params)}",
                    headers=headers,
                    timeout=8,
                )
                if r.ok:
                    d = r.json()
                    if d and d.get("id"):
                        init_data = d
                        init_domain = domain
                        break
            except Exception:
                pass

        if not init_data:
            return False

        if init_data.get("title"):
            self.title_text = init_data["title"]
        thumb = init_data.get("thumbnail_url") or (init_data.get("info") or {}).get(
            "image"
        )
        if thumb:
            self.carregar_thumbnail(thumb)
        self._update_ui(0.10, "Iniciando download: 10%", title=self.title_text)

        job_id = init_data["id"]
        prog_url = (
            init_data.get("progress_url")
            or f"https://{init_domain}/api/progress?id={job_id}"
        )

        download_url = None
        for attempt in range(70):
            if self.is_cancelled:
                return True
            sleep(1.4)
            try:
                rp = requests.get(prog_url, headers=headers, timeout=6)
                if not rp.ok:
                    continue
                jp = rp.json()
                raw_p = jp.get("progress") or 0
                pct = min(95, max(10, int(raw_p / 10)))
                self._update_ui(
                    pct / 100.0, f"Baixando e preparando arquivo: {pct}%"
                )
                if jp.get("download_url") and int(jp.get("success") or 0) == 1:
                    download_url = jp["download_url"]
                    break
            except Exception:
                pass

        if not download_url or self.is_cancelled:
            return False

        # Salva o stream diretamente na pasta de Downloads do computador
        base_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", self.title_text).strip()
        base_name = base_name.rstrip(". ")[:150] or "video_download"
        if self.trim_range and (self.trim_range[0] or self.trim_range[1]):
            base_name += "_recorte"
        nome_final_unico = self.gerar_nome_unico(f"{base_name}.{ext_final}")
        path_final = os.path.join(self.folder, nome_final_unico)

        self._update_ui(0.96, "Transferindo para o seu computador...")
        with requests.get(download_url, headers=headers, stream=True, timeout=30) as r_dl:
            r_dl.raise_for_status()
            total = int(r_dl.headers.get("content-length") or 0)
            baixado = 0
            with open(path_final, "wb") as f:
                for chunk in r_dl.iter_content(chunk_size=131072):
                    if self.is_cancelled:
                        break
                    if chunk:
                        f.write(chunk)
                        baixado += len(chunk)
                        if total > 0:
                            p_dl = 0.95 + 0.05 * (baixado / total)
                            self._update_ui(
                                p_dl,
                                f"Salvando no disco: {(baixado / (1024*1024)):.1f} MB",
                            )

        if self.is_cancelled:
            try:
                os.remove(path_final)
            except Exception:
                pass
            return True

        self._update_ui(
            1.0,
            "Concluído! Arquivo salvo no seu computador.",
            finished=True,
            final_path=path_final,
            color=self.color_mode,
        )
        return True

    def _logic_completa(self):
        try:
            clean_url = self.url.split("?turnstile")[0].strip()
            ext_final = "mp3" if self.mode == "audio" else "mp4"
            creation_flags = (
                subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            # Se o FFmpeg ou yt-dlp ainda estiverem baixando em segundo plano e não exigir cookies locais,
            # usa imediatamente o Motor Online (mesmo motor da versão Web) sem fazer o usuário esperar!
            yt_dlp_bin = self.tools_path.get("yt-dlp")
            ffmpeg_bin = self.tools_path.get("ffmpeg")
            tools_ready = bool(
                yt_dlp_bin
                and os.path.exists(yt_dlp_bin)
                and ffmpeg_bin
                and os.path.exists(ffmpeg_bin)
            )

            if not tools_ready and self.auth_config.get("type") == "none":
                if self._try_cloud_direct_download(clean_url, ext_final):
                    return

            # Caso precise do yt-dlp local, aguarda ficar pronto
            if self.ytdlp_ready_event and not self.ytdlp_ready_event.is_set():
                self._update_ui(0.02, "⏳ Preparando motor de download...")
                while not self.ytdlp_ready_event.wait(0.3):
                    if self.is_cancelled:
                        return

            yt_dlp_bin = self.tools_path.get("yt-dlp")
            if not yt_dlp_bin or not os.path.exists(yt_dlp_bin):
                if self._try_cloud_direct_download(clean_url, ext_final):
                    return
                raise RuntimeError("Motor de download ainda não disponível.")

            # 1. OBTENÇÃO DE METADADOS
            if self.prefetched_info and self.prefetched_info.get("title"):
                self.title_text = self.prefetched_info["title"]
                thumb_url = self.prefetched_info.get("thumbnail")
                if thumb_url:
                    self.carregar_thumbnail(thumb_url)
                self._update_ui(0.08, "Preparando download...", title=self.title_text)
            else:
                self._update_ui(0.04, "Obtendo informações do vídeo...")
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
                    # Fallback automático para o Motor Online!
                    if self._try_cloud_direct_download(clean_url, ext_final):
                        return
                    raise RuntimeError("Não foi possível ler este link.")

                json_line = ""
                for line in res.stdout.splitlines():
                    if line.strip().startswith("{"):
                        json_line = line.strip()
                        break

                if json_line:
                    info = json.loads(json_line)
                    self.title_text = info.get("title") or "Video_Download"
                    thumb_url = info.get("thumbnail")
                    if thumb_url:
                        self.carregar_thumbnail(thumb_url)
                self._update_ui(0.08, "Preparando arquivo...", title=self.title_text)

            # Se o FFmpeg ainda estiver baixando, tenta finalizar pelo Motor Online imediatamente
            if self.ffmpeg_ready_event and not self.ffmpeg_ready_event.is_set():
                if self.auth_config.get("type") == "none":
                    if self._try_cloud_direct_download(clean_url, ext_final):
                        return
                self._update_ui(
                    0.09,
                    "⏳ Aguardando FFmpeg finalizar instalação...",
                    title=self.title_text,
                )
                while not self.ffmpeg_ready_event.wait(0.3):
                    if self.is_cancelled:
                        return

            # 2. CÁLCULO DE NOME ÚNICO
            base_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", self.title_text).strip()
            base_name = base_name.rstrip(". ")[:150] or "video_download"
            if self.trim_range and (self.trim_range[0] or self.trim_range[1]):
                base_name += "_recorte"

            nome_correto = f"{base_name}.{ext_final}"
            nome_final_unico = self.gerar_nome_unico(nome_correto)
            stem_unico = os.path.splitext(nome_final_unico)[0]

            output_template = os.path.join(self.folder, f"{stem_unico}.%(ext)s")
            path_final_esperado = os.path.join(self.folder, nome_final_unico)
            self.final_absolute_path = path_final_esperado

            # 3. COMANDO DE DOWNLOAD
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
                        [
                            "--format",
                            "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best",
                        ]
                    )
                elif "1080p" in self.quality:
                    cmd_down.extend(
                        [
                            "--format",
                            "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                        ]
                    )
                elif "720p" in self.quality:
                    cmd_down.extend(
                        [
                            "--format",
                            "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                        ]
                    )
                elif "480p" in self.quality:
                    cmd_down.extend(
                        [
                            "--format",
                            "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
                        ]
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

            self.processo = subprocess.Popen(
                cmd_down,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creation_flags,
                encoding="utf-8",
                errors="replace",
            )

            for line in self.processo.stdout:
                if self.is_cancelled:
                    break
                line_s = line.strip()
                match = re.search(r"\[download\]\s+(\d+\.?\d*)%", line_s)
                if match:
                    pct = float(match.group(1))
                    speed_m = re.search(r"at\s+([0-9.]+[A-Za-z/]+)", line_s)
                    speed_txt = f" ({speed_m.group(1)})" if speed_m else ""
                    self._update_ui(
                        pct / 100.0,
                        f"Baixando e preparando arquivo: {pct:.0f}%{speed_txt}",
                    )
                elif "[ExtractAudio]" in line_s:
                    self._update_ui(0.98, "Extraindo áudio MP3...")
                elif "[Merger]" in line_s or "Merging formats" in line_s:
                    self._update_ui(0.98, "Finalizando arquivo MP4...")

            self.processo.wait()

            if self.is_cancelled:
                return

            if not os.path.exists(path_final_esperado):
                for ext_cand in [ext_final, "mp4", "mkv", "webm", "mp3", "m4a"]:
                    cand = os.path.join(self.folder, f"{stem_unico}.{ext_cand}")
                    if os.path.exists(cand):
                        path_final_esperado = cand
                        break

            if self.processo.returncode == 0 and os.path.exists(path_final_esperado):
                self._update_ui(
                    1.0,
                    "Concluído! Arquivo salvo no seu computador.",
                    finished=True,
                    final_path=path_final_esperado,
                    color=self.color_mode,
                )
            else:
                if self._try_cloud_direct_download(clean_url, ext_final):
                    return
                self._update_ui(
                    0, "Erro ao processar vídeo (Verifique o link).", color=DANGER_COLOR
                )

        except Exception as e:
            if not self.is_cancelled:
                self._update_ui(
                    0, f"Erro: {str(e)[:65]}", title="Falha no Download", color=DANGER_COLOR
                )


class ConverterItem(ctk.CTkFrame):
    """Card individual de conversão e recorte local com progresso real."""

    def __init__(
        self,
        master,
        filepath,
        output_folder,
        tools_path,
        target_format,
        trim_range=None,
        ffmpeg_ready_event=None,
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color=BG_ELEVATED,
            corner_radius=12,
            border_width=1,
            border_color=BORDER_COLOR,
            **kwargs,
        )
        self.filepath = filepath
        self.output_folder = output_folder
        self.tools = tools_path
        self.target_format = target_format
        self.trim_range = trim_range
        self.ffmpeg_ready_event = ffmpeg_ready_event
        self.grid_columnconfigure(1, weight=1)

        if target_format in ("mp3", "wav"):
            icon = "🎵"
            self.color = BLUE_AUDIO
        else:
            icon = "🎬"
            self.color = GREEN_BRIGHT

        filename = os.path.basename(filepath)
        self.lbl_icon = ctk.CTkLabel(
            self,
            text=icon,
            width=96,
            height=60,
            fg_color="#10131a",
            corner_radius=8,
            font=("Segoe UI", 22),
        )
        self.lbl_icon.grid(row=0, column=0, rowspan=3, padx=14, pady=12)

        self.lbl_status = ctk.CTkLabel(
            self,
            text=f"Convertendo para {target_format.upper()}...",
            anchor="w",
            text_color=TEXT_MUTED,
            font=("Segoe UI", 12, "bold"),
        )
        self.lbl_status.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 0))

        self.lbl_title = ctk.CTkLabel(
            self,
            text=filename,
            anchor="w",
            font=("Segoe UI", 14, "bold"),
            text_color=TEXT_MAIN,
        )
        self.lbl_title.grid(row=1, column=1, sticky="ew", padx=(0, 12))

        self.progress = ctk.CTkProgressBar(
            self, height=9, corner_radius=99, fg_color="#0f131a"
        )
        self.progress.configure(progress_color=self.color)
        self.progress.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=(6, 12))
        self.progress.set(0.08)

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
                self.configure(border_color=GREEN_BRIGHT)
                btn_open = ctk.CTkButton(
                    self,
                    text="📂 Abrir Arquivo",
                    width=125,
                    height=34,
                    corner_radius=8,
                    font=("Segoe UI", 12, "bold"),
                    fg_color=self.color,
                    text_color=GREEN_DARK_TEXT
                    if self.target_format == "mp4"
                    else "#ffffff",
                    command=lambda: subprocess.run(
                        ["explorer", "/select,", os.path.normpath(output_file)]
                    ),
                )
                btn_open.grid(row=0, column=2, rowspan=3, padx=14)

        self.after(0, _apply)

    def _convert(self):
        try:
            if self.ffmpeg_ready_event and not self.ffmpeg_ready_event.is_set():
                self._update_conv_ui(
                    0.05,
                    "⏳ Na fila (Aguardando download do FFmpeg concluir)...",
                    color="#FBBF24",
                )
                self.ffmpeg_ready_event.wait()

            filename = os.path.splitext(os.path.basename(self.filepath))[0]
            suffix = (
                "_recorte"
                if self.trim_range and (self.trim_range[0] or self.trim_range[1])
                else ""
            )
            output_file = os.path.join(
                self.output_folder, f"{filename}{suffix}.{self.target_format}"
            )
            count = 1
            base = output_file
            while os.path.exists(output_file):
                output_file = (
                    f"{os.path.splitext(base)[0]} ({count}).{self.target_format}"
                )
                count += 1

            ffmpeg = self.tools.get("ffmpeg")
            while not ffmpeg or not os.path.exists(ffmpeg):
                sleep(0.5)
                ffmpeg = self.tools.get("ffmpeg")

            cmd = [ffmpeg, "-y"]
            if self.trim_range and self.trim_range[0]:
                cmd.extend(["-ss", self.trim_range[0]])
            if self.trim_range and self.trim_range[1]:
                cmd.extend(["-to", self.trim_range[1]])
            cmd.extend(["-i", self.filepath])

            if self.target_format == "mp4":
                cmd.extend(
                    [
                        "-c:v",
                        "libx264",
                        "-preset",
                        "fast",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        output_file,
                    ]
                )
            elif self.target_format == "mp3":
                cmd.extend(
                    ["-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k", output_file]
                )
            else:
                cmd.extend(["-vn", "-ar", "44100", "-ac", "2", output_file])

            creation_flags = (
                subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
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
                    f"Conversão Concluída! Salvo em Downloads.",
                    color=self.color,
                    output_file=output_file,
                )
            else:
                raise RuntimeError("Falha ao converter arquivo com FFmpeg.")
        except Exception as e:
            self._update_conv_ui(0.0, f"Erro: {e}", color=DANGER_COLOR)


class App(ctk.CTk):
    """Aplicativo Desktop com visual e recursos idênticos à versão Web Online."""

    def __init__(self):
        super().__init__()
        self.title("Multimídia Esperança Downloader")
        self.geometry("1040x780")
        self.minsize(920, 680)
        self.configure(fg_color=BG_DARK)

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
        self.current_mode = "video"

        # Layout Principal (Shell)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.setup_header()
        self.setup_navigation_bar()
        self.setup_panels()
        self.setup_footer()

        self.switch_tab("downloader")

        self.after(
            150,
            lambda: threading.Thread(
                target=self.manage_tools, args=(False,), daemon=True
            ).start(),
        )

    # --- PERSISTÊNCIA ---
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
        self.history_data = self.history_data[:100]
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        self.refresh_history_ui()

    # --- CABEÇALHO (IDÊNTICO AO WEB: LOGO TV ESPERANÇA + TÍTULO + SERVIDOR ONLINE) ---
    def setup_header(self):
        self.header_card = ctk.CTkFrame(
            self,
            fg_color=BG_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        self.header_card.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        self.header_card.grid_columnconfigure(1, weight=1)

        # Logo TV Esperança
        logo_box = ctk.CTkFrame(
            self.header_card,
            width=78,
            height=64,
            fg_color="#000000",
            corner_radius=12,
            border_width=1,
            border_color=GREEN_BRIGHT,
        )
        logo_box.grid(row=0, column=0, padx=(18, 14), pady=14)
        logo_box.grid_propagate(False)

        try:
            logo_img = Image.open(resource_path("logo.png"))
            self.ctk_logo = ctk.CTkImage(
                light_image=logo_img, dark_image=logo_img, size=(66, 54)
            )
            lbl_logo = ctk.CTkLabel(logo_box, image=self.ctk_logo, text="")
            lbl_logo.place(relx=0.5, rely=0.5, anchor="center")
        except Exception:
            lbl_logo = ctk.CTkLabel(
                logo_box,
                text="TV",
                font=("Segoe UI", 18, "bold"),
                text_color=GREEN_BRIGHT,
            )
            lbl_logo.place(relx=0.5, rely=0.5, anchor="center")

        # Textos do Título e Subtítulo
        title_frame = ctk.CTkFrame(self.header_card, fg_color="transparent")
        title_frame.grid(row=0, column=1, sticky="w", pady=14)

        ctk.CTkLabel(
            title_frame,
            text="Multimídia Esperança Downloader",
            font=("Segoe UI", 21, "bold"),
            text_color=TEXT_MAIN,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame,
            text="Download direto de vídeos em até 4K, extração de áudio MP3 e recorte inteligente",
            font=("Segoe UI", 12),
            text_color=TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # Status Pill Direito ("● Servidor Online")
        self.status_pill = ctk.CTkButton(
            self.header_card,
            text="●  Servidor Online",
            height=34,
            corner_radius=999,
            fg_color="#112a22",
            hover_color="#17382d",
            border_width=1,
            border_color="#1e4d3b",
            text_color=GREEN_BRIGHT,
            font=("Segoe UI", 12, "bold"),
            command=self.start_update,
        )
        self.status_pill.grid(row=0, column=2, padx=18, pady=14)

    # --- BARRA DE ABAS ESTILO STUDIO WEB ---
    def setup_navigation_bar(self):
        self.nav_bar = ctk.CTkFrame(
            self,
            fg_color=BG_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        self.nav_bar.grid(row=1, column=0, sticky="ew", padx=20, pady=6)
        self.nav_bar.grid_columnconfigure((0, 1, 2), weight=1)

        self.btn_tab_down = ctk.CTkButton(
            self.nav_bar,
            text="⬇  DOWNLOADER",
            height=40,
            corner_radius=10,
            font=("Segoe UI", 13, "bold"),
            command=lambda: self.switch_tab("downloader"),
        )
        self.btn_tab_down.grid(row=0, column=0, sticky="ew", padx=(6, 4), pady=6)

        self.btn_tab_conv = ctk.CTkButton(
            self.nav_bar,
            text="🔄  CONVERSOR & RECORTADOR",
            height=40,
            corner_radius=10,
            font=("Segoe UI", 13, "bold"),
            command=lambda: self.switch_tab("converter"),
        )
        self.btn_tab_conv.grid(row=0, column=1, sticky="ew", padx=4, pady=6)

        self.btn_tab_hist = ctk.CTkButton(
            self.nav_bar,
            text=f"📜  HISTÓRICO ({len(self.history_data)})",
            height=40,
            corner_radius=10,
            font=("Segoe UI", 13, "bold"),
            command=lambda: self.switch_tab("history"),
        )
        self.btn_tab_hist.grid(row=0, column=2, sticky="ew", padx=(4, 6), pady=6)

    def switch_tab(self, tab_name):
        for name, btn in [
            ("downloader", self.btn_tab_down),
            ("converter", self.btn_tab_conv),
            ("history", self.btn_tab_hist),
        ]:
            if name == tab_name:
                btn.configure(
                    fg_color=GREEN_BRIGHT,
                    text_color=GREEN_DARK_TEXT,
                    hover_color=GREEN_HOVER,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=TEXT_MUTED,
                    hover_color="#202634",
                )

        self.panel_downloader.grid_forget()
        self.panel_converter.grid_forget()
        self.panel_history.grid_forget()

        if tab_name == "downloader":
            self.panel_downloader.grid(
                row=2, column=0, sticky="nsew", padx=20, pady=6
            )
        elif tab_name == "converter":
            self.panel_converter.grid(
                row=2, column=0, sticky="nsew", padx=20, pady=6
            )
        elif tab_name == "history":
            self.panel_history.grid(
                row=2, column=0, sticky="nsew", padx=20, pady=6
            )

    def setup_panels(self):
        self.panel_downloader = ctk.CTkFrame(self, fg_color="transparent")
        self.panel_converter = ctk.CTkFrame(self, fg_color="transparent")
        self.panel_history = ctk.CTkFrame(self, fg_color="transparent")

        self.build_downloader_panel()
        self.build_converter_panel()
        self.build_history_panel()

    # --- PAINEL 1: DOWNLOADER (IDÊNTICO À VERSÃO ONLINE) ---
    def build_downloader_panel(self):
        self.panel_downloader.grid_columnconfigure(0, weight=1)
        self.panel_downloader.grid_rowconfigure(1, weight=1)

        # Card de Controles Superior
        ctrl_card = ctk.CTkFrame(
            self.panel_downloader,
            fg_color=BG_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        ctrl_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ctrl_card.grid_columnconfigure(0, weight=1)

        # Linha 1: Input de Link + Colar Link
        row1 = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        row1.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        row1.grid_columnconfigure(0, weight=1)

        self.entry_link = ctk.CTkEntry(
            row1,
            placeholder_text="🔗  Cole o link do YouTube, TikTok, Instagram, Facebook, X ou Vimeo aqui...",
            height=44,
            corner_radius=10,
            fg_color=BG_INPUT,
            border_color="#2a3244",
            text_color=TEXT_MAIN,
            font=("Segoe UI", 13),
        )
        self.entry_link.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.entry_link.bind("<Return>", lambda e: self.preparar_download())

        self.btn_paste = ctk.CTkButton(
            row1,
            text="📋 Colar Link",
            width=125,
            height=44,
            corner_radius=10,
            fg_color="#222936",
            hover_color="#2d3646",
            border_width=1,
            border_color="#333d52",
            text_color=TEXT_MAIN,
            font=("Segoe UI", 13, "bold"),
            command=self.colar_link,
        )
        self.btn_paste.grid(row=0, column=1)

        # Linha 2: Botões de Modo (Vídeo/Áudio), Qualidade, Escopo, Legendas, BAIXAR AGORA
        row2 = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        row2.grid(row=1, column=0, sticky="ew", padx=18, pady=6)

        mode_box = ctk.CTkFrame(
            row2,
            fg_color=BG_INPUT,
            corner_radius=10,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        mode_box.pack(side="left", padx=(0, 10))

        self.btn_mode_video = ctk.CTkButton(
            mode_box,
            text="🎬 VÍDEO (MP4)",
            width=125,
            height=34,
            corner_radius=7,
            fg_color=GREEN_BRIGHT,
            text_color=GREEN_DARK_TEXT,
            hover_color=GREEN_HOVER,
            font=("Segoe UI", 12, "bold"),
            command=lambda: self.set_mode("video"),
        )
        self.btn_mode_video.pack(side="left", padx=4, pady=4)

        self.btn_mode_audio = ctk.CTkButton(
            mode_box,
            text="🎵 ÁUDIO (MP3)",
            width=125,
            height=34,
            corner_radius=7,
            fg_color="transparent",
            text_color=TEXT_MUTED,
            hover_color="#1d2432",
            font=("Segoe UI", 12, "bold"),
            command=lambda: self.set_mode("audio"),
        )
        self.btn_mode_audio.pack(side="left", padx=(0, 4), pady=4)

        # Qualidade
        qual_box = ctk.CTkFrame(
            row2,
            fg_color=BG_INPUT,
            corner_radius=10,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        qual_box.pack(side="left", padx=5)
        ctk.CTkLabel(
            qual_box,
            text="QUALIDADE",
            font=("Segoe UI", 10, "bold"),
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(10, 4), pady=6)
        self.quality_menu = ctk.CTkOptionMenu(
            qual_box,
            values=["4K Ultra HD", "1080p Full HD", "720p HD", "480p Leve"],
            width=130,
            height=30,
            fg_color=BG_INPUT,
            button_color="#1e2534",
            button_hover_color="#2a3346",
            font=("Segoe UI", 12, "bold"),
        )
        self.quality_menu.set("1080p Full HD")
        self.quality_menu.pack(side="left", padx=(0, 6), pady=6)

        # Modo (Vídeo Único / Playlist)
        scope_box = ctk.CTkFrame(
            row2,
            fg_color=BG_INPUT,
            corner_radius=10,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        scope_box.pack(side="left", padx=5)
        ctk.CTkLabel(
            scope_box,
            text="MODO",
            font=("Segoe UI", 10, "bold"),
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(10, 4), pady=6)
        self.playlist_scope = ctk.CTkOptionMenu(
            scope_box,
            values=["Vídeo Único", "Playlist"],
            width=115,
            height=30,
            fg_color=BG_INPUT,
            button_color="#1e2534",
            button_hover_color="#2a3346",
            font=("Segoe UI", 12, "bold"),
        )
        self.playlist_scope.set("Vídeo Único")
        self.playlist_scope.pack(side="left", padx=(0, 6), pady=6)

        # Legendas
        subs_box = ctk.CTkFrame(
            row2,
            fg_color=BG_INPUT,
            corner_radius=10,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        subs_box.pack(side="left", padx=5)
        self.check_subs = ctk.CTkCheckBox(
            subs_box,
            text="💬 Legendas",
            font=("Segoe UI", 12, "bold"),
            checkbox_width=18,
            checkbox_height=18,
            fg_color=GREEN_BRIGHT,
            checkmark_color=GREEN_DARK_TEXT,
        )
        self.check_subs.pack(padx=12, pady=9)

        # Botão Principal: ⬇ BAIXAR AGORA
        self.btn_download = ctk.CTkButton(
            row2,
            text="⬇  BAIXAR AGORA",
            width=165,
            height=42,
            corner_radius=10,
            font=("Segoe UI", 13, "bold"),
            fg_color=GREEN_BRIGHT,
            text_color=GREEN_DARK_TEXT,
            hover_color=GREEN_HOVER,
            command=self.preparar_download,
        )
        self.btn_download.pack(side="right")

        # Linha 3: Barra de Recorte de Trecho Específico + Tags de Plataforma + Cookies
        row3 = ctk.CTkFrame(
            ctrl_card,
            fg_color=BG_SUBROW,
            corner_radius=10,
            border_width=1,
            border_color="#1b212e",
        )
        row3.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 18))

        self.check_trim = ctk.CTkCheckBox(
            row3,
            text="✂️ Recortar Trecho Específico:",
            command=self.toggle_trim_inputs,
            font=("Segoe UI", 12, "bold"),
            checkbox_width=18,
            checkbox_height=18,
            fg_color=GREEN_BRIGHT,
            checkmark_color=GREEN_DARK_TEXT,
        )
        self.check_trim.pack(side="left", padx=(14, 8), pady=10)

        self.entry_trim_start = ctk.CTkEntry(
            row3,
            placeholder_text="Início (00:01:00)",
            width=125,
            height=32,
            corner_radius=8,
            fg_color=BG_INPUT,
            state="disabled",
        )
        self.entry_trim_start.pack(side="left", padx=4, pady=10)

        ctk.CTkLabel(row3, text="até", text_color=TEXT_MUTED).pack(
            side="left", padx=4
        )

        self.entry_trim_end = ctk.CTkEntry(
            row3,
            placeholder_text="Fim (00:02:30)",
            width=125,
            height=32,
            corner_radius=8,
            fg_color=BG_INPUT,
            state="disabled",
        )
        self.entry_trim_end.pack(side="left", padx=4, pady=10)

        # Seletor de Cookies discreto + Tags de plataformas
        self.auth_menu = ctk.CTkOptionMenu(
            row3,
            values=[
                "Público (Sem Login)",
                "Cookies: Chrome",
                "Cookies: Edge",
                "Cookies: Firefox",
                "Cookies: Brave",
                "Cookies: Arquivo .txt",
            ],
            width=155,
            height=28,
            corner_radius=7,
            fg_color="#181e29",
            button_color="#232b3a",
            font=("Segoe UI", 11),
            command=self.on_auth_change,
        )
        self.auth_menu.set("Público (Sem Login)")
        self.auth_menu.pack(side="right", padx=10, pady=10)

        for tag in ("Facebook", "Instagram", "TikTok s/ Marca", "YouTube"):
            lbl_t = ctk.CTkLabel(
                row3,
                text=tag,
                fg_color="#181e29",
                corner_radius=6,
                text_color=TEXT_MUTED,
                font=("Segoe UI", 11, "bold"),
                padx=8,
                pady=2,
            )
            lbl_t.pack(side="right", padx=3)

        # Seção Fila de Downloads
        queue_card = ctk.CTkFrame(
            self.panel_downloader,
            fg_color=BG_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        queue_card.grid(row=1, column=0, sticky="nsew")
        queue_card.grid_columnconfigure(0, weight=1)
        queue_card.grid_rowconfigure(1, weight=1)

        q_header = ctk.CTkFrame(queue_card, fg_color="transparent")
        q_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))

        ctk.CTkLabel(
            q_header,
            text="FILA DE DOWNLOADS",
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT_MAIN,
        ).pack(side="left")

        ctk.CTkLabel(
            q_header,
            text="⚡ O arquivo é salvo automaticamente no seu computador ao atingir 100%",
            fg_color="#112a22",
            text_color=GREEN_BRIGHT,
            corner_radius=99,
            font=("Segoe UI", 11, "bold"),
            padx=10,
            pady=3,
        ).pack(side="left", padx=12)

        ctk.CTkButton(
            q_header,
            text="Limpar concluídos",
            width=120,
            height=28,
            fg_color="transparent",
            hover_color="#202634",
            text_color=TEXT_MUTED,
            font=("Segoe UI", 12, "bold"),
            command=self.clear_completed_downloads,
        ).pack(side="right")

        self.scroll_down = ctk.CTkScrollableFrame(
            queue_card, fg_color="transparent"
        )
        self.scroll_down.grid(
            row=1, column=0, sticky="nsew", padx=12, pady=(0, 12)
        )

        self.empty_down_lbl = ctk.CTkLabel(
            self.scroll_down,
            text="📥\nPronto para baixar\nCole um link de vídeo ou música acima e clique em Baixar Agora. O download iniciará automaticamente.",
            font=("Segoe UI", 13),
            text_color=TEXT_MUTED,
            justify="center",
        )
        self.empty_down_lbl.pack(pady=45)

    # --- PAINEL 2: CONVERSOR & RECORTADOR LOCAL (IDÊNTICO AO WEB) ---
    def build_converter_panel(self):
        self.panel_converter.grid_columnconfigure(0, weight=1)
        self.panel_converter.grid_rowconfigure(1, weight=1)

        conv_card = ctk.CTkFrame(
            self.panel_converter,
            fg_color=BG_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        conv_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        conv_card.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(
            conv_card,
            text="Conversor e Recortador de Mídia Local",
            font=("Segoe UI", 16, "bold"),
            text_color=TEXT_MAIN,
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(16, 2))

        ctk.CTkLabel(
            conv_card,
            text="Converta arquivos de vídeo ou áudio do seu computador e recorte trechos instantaneamente.",
            font=("Segoe UI", 12),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 10))

        # Linha de Recorte Opcional
        trim_row = ctk.CTkFrame(
            conv_card, fg_color=BG_SUBROW, corner_radius=10
        )
        trim_row.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 12)
        )

        ctk.CTkLabel(
            trim_row,
            text="✂️ Recorte Opcional:",
            font=("Segoe UI", 12, "bold"),
            text_color=TEXT_MAIN,
        ).pack(side="left", padx=(14, 8), pady=10)

        self.conv_trim_start = ctk.CTkEntry(
            trim_row,
            placeholder_text="Início (00:00)",
            width=130,
            height=32,
            corner_radius=8,
            fg_color=BG_INPUT,
        )
        self.conv_trim_start.pack(side="left", padx=4, pady=10)

        ctk.CTkLabel(trim_row, text="até", text_color=TEXT_MUTED).pack(
            side="left", padx=4
        )

        self.conv_trim_end = ctk.CTkEntry(
            trim_row,
            placeholder_text="Fim (ex: 02:30)",
            width=130,
            height=32,
            corner_radius=8,
            fg_color=BG_INPUT,
        )
        self.conv_trim_end.pack(side="left", padx=4, pady=10)

        # Botões Grandes de Conversão (Verde p/ Vídeo, Azul p/ Áudio)
        self.btn_add_vid = ctk.CTkButton(
            conv_card,
            text="🎬  Converter Vídeo para MP4\nSelecionar vídeos do computador",
            height=64,
            corner_radius=12,
            fg_color=GREEN_BRIGHT,
            text_color=GREEN_DARK_TEXT,
            hover_color=GREEN_HOVER,
            font=("Segoe UI", 14, "bold"),
            command=lambda: self.add_conversion("mp4"),
        )
        self.btn_add_vid.grid(
            row=3, column=0, sticky="ew", padx=(18, 7), pady=(0, 18)
        )

        self.btn_add_aud = ctk.CTkButton(
            conv_card,
            text="🎵  Extrair Áudio de Alta Qualidade (MP3 / WAV)\nDe qualquer arquivo de vídeo ou áudio",
            height=64,
            corner_radius=12,
            fg_color=BLUE_AUDIO,
            text_color="#ffffff",
            hover_color=BLUE_HOVER,
            font=("Segoe UI", 14, "bold"),
            command=lambda: self.add_conversion("mp3"),
        )
        self.btn_add_aud.grid(
            row=3, column=1, sticky="ew", padx=(7, 18), pady=(0, 18)
        )

        # Fila de Arquivos Convertidos
        conv_queue_card = ctk.CTkFrame(
            self.panel_converter,
            fg_color=BG_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        conv_queue_card.grid(row=1, column=0, sticky="nsew")
        conv_queue_card.grid_columnconfigure(0, weight=1)
        conv_queue_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            conv_queue_card,
            text="ARQUIVOS CONVERTIDOS",
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT_MAIN,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 6))

        self.scroll_conv = ctk.CTkScrollableFrame(
            conv_queue_card, fg_color="transparent"
        )
        self.scroll_conv.grid(
            row=1, column=0, sticky="nsew", padx=12, pady=(0, 12)
        )

        self.empty_conv_lbl = ctk.CTkLabel(
            self.scroll_conv,
            text="🔄\nNenhum arquivo na fila\nEscolha um dos botões acima para converter ou extrair o áudio de arquivos do seu PC.",
            font=("Segoe UI", 13),
            text_color=TEXT_MUTED,
            justify="center",
        )
        self.empty_conv_lbl.pack(pady=40)

    # --- PAINEL 3: HISTÓRICO ---
    def build_history_panel(self):
        self.panel_history.grid_columnconfigure(0, weight=1)
        self.panel_history.grid_rowconfigure(0, weight=1)

        hist_card = ctk.CTkFrame(
            self.panel_history,
            fg_color=BG_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        hist_card.grid(row=0, column=0, sticky="nsew")
        hist_card.grid_columnconfigure(0, weight=1)
        hist_card.grid_rowconfigure(1, weight=1)

        top_hist = ctk.CTkFrame(hist_card, fg_color="transparent")
        top_hist.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))

        ctk.CTkLabel(
            top_hist,
            text="HISTÓRICO DE DOWNLOADS RECENTES",
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT_MAIN,
        ).pack(side="left")

        ctk.CTkButton(
            top_hist,
            text="🗑️ Limpar Histórico",
            width=145,
            height=32,
            corner_radius=8,
            fg_color="#3b1d1d",
            hover_color="#5c2626",
            text_color="#fca5a5",
            font=("Segoe UI", 12, "bold"),
            command=self.clear_history,
        ).pack(side="right")

        self.scroll_hist = ctk.CTkScrollableFrame(
            hist_card, fg_color="transparent"
        )
        self.scroll_hist.grid(
            row=1, column=0, sticky="nsew", padx=12, pady=(0, 12)
        )
        self.refresh_history_ui()

    def refresh_history_ui(self):
        if hasattr(self, "btn_tab_hist"):
            self.btn_tab_hist.configure(
                text=f"📜  HISTÓRICO ({len(self.history_data)})"
            )

        for widget in self.scroll_hist.winfo_children():
            widget.destroy()

        if not self.history_data:
            ctk.CTkLabel(
                self.scroll_hist,
                text="📜\nHistórico vazio\nSeus downloads concluídos aparecerão aqui para acesso rápido.",
                font=("Segoe UI", 13),
                text_color=TEXT_MUTED,
                justify="center",
            ).pack(pady=50)
            return

        for item in self.history_data:
            row = ctk.CTkFrame(
                self.scroll_hist,
                fg_color=BG_ELEVATED,
                corner_radius=12,
                border_width=1,
                border_color=BORDER_COLOR,
            )
            row.pack(fill="x", padx=6, pady=5)
            row.grid_columnconfigure(0, weight=1)

            title = item.get("title", "Sem título")
            meta = f"{item.get('date', '')}  •  {item.get('quality', '')}"
            path = item.get("path", "")
            url = item.get("url", "")

            ctk.CTkLabel(
                row,
                text=meta,
                anchor="w",
                font=("Segoe UI", 11, "bold"),
                text_color=TEXT_MUTED,
            ).grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))

            ctk.CTkLabel(
                row,
                text=title[:80] + ("..." if len(title) > 80 else ""),
                anchor="w",
                font=("Segoe UI", 14, "bold"),
                text_color=TEXT_MAIN,
            ).grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 10))

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.grid(row=0, column=1, rowspan=2, padx=12)

            if path and os.path.exists(path):
                ctk.CTkButton(
                    btns,
                    text="▶ Abrir",
                    width=80,
                    height=32,
                    corner_radius=8,
                    fg_color=GREEN_BRIGHT,
                    text_color=GREEN_DARK_TEXT,
                    font=("Segoe UI", 12, "bold"),
                    command=lambda p=path: os.startfile(p)
                    if sys.platform == "win32"
                    else None,
                ).pack(side="left", padx=3)
                ctk.CTkButton(
                    btns,
                    text="📂 Pasta",
                    width=80,
                    height=32,
                    corner_radius=8,
                    fg_color="#283040",
                    font=("Segoe UI", 12, "bold"),
                    command=lambda p=path: subprocess.run(
                        ["explorer", "/select,", os.path.normpath(p)]
                    ),
                ).pack(side="left", padx=3)

            if url:
                ctk.CTkButton(
                    btns,
                    text="🔄 Baixar Novamente",
                    width=145,
                    height=32,
                    corner_radius=8,
                    fg_color="#222936",
                    font=("Segoe UI", 12, "bold"),
                    command=lambda u=url: self.requeue_from_history(u),
                ).pack(side="left", padx=4)

    def requeue_from_history(self, url):
        self.switch_tab("downloader")
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

    # --- RODAPÉ (IDÊNTICO AO WEB + SELETOR DE PASTA) ---
    def setup_footer(self):
        self.footer = ctk.CTkFrame(
            self,
            fg_color=BG_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER_COLOR,
        )
        self.footer.grid(row=3, column=0, sticky="ew", padx=20, pady=(4, 16))
        self.footer.grid_columnconfigure(1, weight=1)

        self.btn_folder = ctk.CTkButton(
            self.footer,
            text="📁 Alterar Pasta",
            width=130,
            height=30,
            corner_radius=8,
            fg_color="#222936",
            hover_color="#2d3646",
            font=("Segoe UI", 12, "bold"),
            command=self.sel_folder,
        )
        self.btn_folder.grid(row=0, column=0, padx=12, pady=10)

        self.lbl_folder = ctk.CTkLabel(
            self.footer,
            text=f"Os arquivos concluídos são transferidos diretamente para: {self.download_folder}",
            text_color=TEXT_MUTED,
            anchor="w",
            font=("Segoe UI", 12),
        )
        self.lbl_folder.grid(row=0, column=1, sticky="ew", padx=6)

        ctk.CTkLabel(
            self.footer,
            text="Multimídia Esperança Downloader",
            text_color=TEXT_MUTED,
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=2, padx=16, pady=10)

    # --- AÇÕES E HELPERS DA UI ---
    def set_mode(self, mode):
        self.current_mode = mode
        if mode == "video":
            self.btn_mode_video.configure(
                fg_color=GREEN_BRIGHT, text_color=GREEN_DARK_TEXT
            )
            self.btn_mode_audio.configure(
                fg_color="transparent", text_color=TEXT_MUTED
            )
            self.quality_menu.configure(state="normal")
            self.check_subs.configure(state="normal")
        else:
            self.btn_mode_audio.configure(
                fg_color=BLUE_AUDIO, text_color="#ffffff"
            )
            self.btn_mode_video.configure(
                fg_color="transparent", text_color=TEXT_MUTED
            )
            self.quality_menu.configure(state="disabled")
            self.check_subs.configure(state="disabled")

    def toggle_trim_inputs(self):
        state = "normal" if self.check_trim.get() else "disabled"
        self.entry_trim_start.configure(state=state)
        self.entry_trim_end.configure(state=state)

    def on_auth_change(self, choice):
        if "Arquivo .txt" in choice:
            f = filedialog.askopenfilename(
                filetypes=[("Cookies Netscape TXT", "*.txt")]
            )
            if f:
                self.cookie_file = f
                self._save_settings()

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
            self.lbl_folder.configure(
                text=f"Os arquivos concluídos são transferidos diretamente para: {d}"
            )
            self._save_settings()

    def clear_completed_downloads(self):
        for w in list(self.scroll_down.winfo_children()):
            if isinstance(w, DownloadItem) and getattr(w, "is_done", False):
                w.destroy()
        self._check_empty_download_queue()

    def _check_empty_download_queue(self):
        items = [
            w
            for w in self.scroll_down.winfo_children()
            if isinstance(w, DownloadItem)
        ]
        if not items:
            self.empty_down_lbl.pack(pady=45)
        else:
            self.empty_down_lbl.pack_forget()

    def add_conversion(self, target_format):
        trim_range = None
        ini_raw = self.conv_trim_start.get().strip()
        fim_raw = self.conv_trim_end.get().strip()
        if ini_raw or fim_raw:
            try:
                trim_range = (
                    validar_tempo_corte(ini_raw),
                    validar_tempo_corte(fim_raw),
                )
            except ValueError as err:
                return messagebox.showerror("Tempo Inválido", str(err))

        filetypes = (
            [("Vídeos", "*.mp4;*.mkv;*.avi;*.mov;*.webm;*.flv;*.ts")]
            if target_format == "mp4"
            else [
                (
                    "Mídia de Áudio/Vídeo",
                    "*.mp4;*.mkv;*.webm;*.mp3;*.wav;*.m4a;*.ogg;*.flac",
                )
            ]
        )
        files = filedialog.askopenfilenames(filetypes=filetypes)
        if files:
            self.empty_conv_lbl.pack_forget()
        for f in files:
            ConverterItem(
                self.scroll_conv,
                f,
                self.download_folder,
                self.tools,
                target_format,
                trim_range=trim_range,
                ffmpeg_ready_event=self.ffmpeg_ready_event,
            ).pack(fill="x", padx=6, pady=6)

    # --- GERENCIAMENTO DE COMPONENTES EM SEGUNDO PLANO ---
    def _set_tools_status(self, text, color=GREEN_BRIGHT):
        def _apply():
            self.status_pill.configure(text=text, text_color=color)

        self.after(0, _apply)

    def start_update(self):
        self._set_tools_status("⏳ Atualizando...", color="#FBBF24")
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
                            f"⬇ {label_prefix}: {pct*100:.0f}%", color="#60a5fa"
                        )

    def manage_tools(self, force=False):
        yt = os.path.join(self.bin_dir, "yt-dlp.exe")
        ff = os.path.join(self.bin_dir, "ffmpeg.exe")
        sys_yt = shutil.which("yt-dlp")
        sys_ff = shutil.which("ffmpeg")

        try:
            if not os.path.exists(yt) or force:
                if force and os.path.exists(yt):
                    creation_flags = (
                        subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
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
                        "Motor",
                    )

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
                        "FFmpeg",
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
            self._set_tools_status("●  Servidor Online", color=GREEN_BRIGHT)
        except Exception:
            self.tools = {
                "yt-dlp": yt if os.path.exists(yt) else sys_yt,
                "ffmpeg": ff if os.path.exists(ff) else sys_ff,
            }
            if self.tools["yt-dlp"]:
                self.ytdlp_ready_event.set()
            self.ffmpeg_ready_event.set()
            self._set_tools_status("●  Servidor Online", color=GREEN_BRIGHT)

    # --- PREPARAÇÃO DE DOWNLOAD ---
    def preparar_download(self):
        url = self.entry_link.get().strip()
        if not url:
            return

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

        mode = self.current_mode
        quality = self.quality_menu.get()
        subs = bool(self.check_subs.get())
        auth_config = self._get_current_auth_config()
        is_playlist = self.playlist_scope.get() == "Playlist"

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
            self.empty_down_lbl.pack_forget()
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
                on_remove_callback=self._check_empty_download_queue,
                ytdlp_ready_event=self.ytdlp_ready_event,
                ffmpeg_ready_event=self.ffmpeg_ready_event,
            )
            item.pack(fill="x", padx=6, pady=6)
            item.start()

        self.after(0, _add)

    def _expandir_playlist(self, url, mode, quality, subs, auth_config, trim_range):
        try:
            if not self.ytdlp_ready_event.is_set():
                self.ytdlp_ready_event.wait()

            yt_dlp_bin = self.tools["yt-dlp"]
            cmd = [
                yt_dlp_bin,
                "--flat-playlist",
                "--dump-single-json",
                "--no-warnings",
                url,
            ]
            creation_flags = (
                subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
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
                self._adicionar_item_fila(
                    url, mode, quality, subs, auth_config, trim_range
                )
                return

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
                    vid_url,
                    mode,
                    quality,
                    subs,
                    auth_config,
                    trim_range,
                    prefetched,
                )
        except Exception:
            self._adicionar_item_fila(
                url, mode, quality, subs, auth_config, trim_range
            )


if __name__ == "__main__":
    App().mainloop()
