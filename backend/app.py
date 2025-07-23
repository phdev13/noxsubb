from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request, BackgroundTasks, Response, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import yt_dlp
from urllib.parse import urlparse
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
import os,json,time,uuid,asyncio,logging,tempfile,subprocess,threading,shutil,concurrent.futures,psutil,torch
from faster_whisper import WhisperModel

# --- Modelos Pydantic para Validação de Requisições ---

# Usado para baixar um vídeo completo do YouTube
class YouTubeDownloadRequest(BaseModel):
    url: str
    quality: str = 'best' # Opções: best, 720p, 480p, audio

# Usado para buscar apenas os metadados (título, miniatura, etc.) de um vídeo
class YouTubeURLRequest(BaseModel):
    url: str

# --- Configuração de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuração de Hardware e Modelo ---
CPU_CORES = os.cpu_count() or 1
MEMORY_GB = psutil.virtual_memory().total / (1024**3)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
COMPUTE_TYPE = "float16" if DEVICE == "cuda" else "int8"

if MEMORY_GB <= 4:
    HARDWARE_TIER, DEFAULT_MODEL, MAX_WORKERS, BEAM_SIZE = "low", "tiny", 1, 1
elif MEMORY_GB <= 8:
    HARDWARE_TIER, DEFAULT_MODEL, MAX_WORKERS, BEAM_SIZE = "medium", "base", min(2, CPU_CORES), 1
elif MEMORY_GB <= 16:
    HARDWARE_TIER, DEFAULT_MODEL, MAX_WORKERS, BEAM_SIZE = "high", "small", min(4, CPU_CORES), 1
else:
    HARDWARE_TIER, DEFAULT_MODEL, MAX_WORKERS, BEAM_SIZE = "ultra", "medium", min(8, CPU_CORES), 1

# Parâmetros otimizados para transcrição rápida com Whisper
ULTRA_SPEED_CONFIG = {
    "beam_size": BEAM_SIZE, "best_of": 1, "patience": 1, "length_penalty": 1, "repetition_penalty": 1.0,
    "temperature": [0.0], "compression_ratio_threshold": 2.4, "log_prob_threshold": -1.0,
    "no_speech_threshold": 0.6, "condition_on_previous_text": False, "suppress_blank": True,
    "suppress_tokens": [-1], "without_timestamps": False, "vad_filter": True,
    "vad_parameters": {"threshold": 0.5, "min_speech_duration_ms": 250, "max_speech_duration_s": float("inf"),
                      "min_silence_duration_ms": 1000, "speech_pad_ms": 200}
}

logger.info(f"Config: {HARDWARE_TIER} - {MEMORY_GB:.1f}GB - {CPU_CORES}c - {DEVICE} - {DEFAULT_MODEL}")

# --- Inicialização da Aplicação FastAPI ---
app = FastAPI(title="Video Processing API", version="5.0.0")

# Middleware para permitir requisições de diferentes origens (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# --- Configurações Globais e Constantes ---
FILES_DIR = os.path.join(os.getcwd(), "files")
os.makedirs(FILES_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=FILES_DIR), name="files")

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
ALLOWED_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v'}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB
LANGUAGES = {'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German', 'it': 'Italian', 'ja': 'Japanese', 'ko': 'Korean', 'zh': 'Chinese', 'ru': 'Russian', 'ar': 'Arabic', 'pt': 'Portuguese'}

executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
status_cache = {} # Cache simples em memória para status
whisper_models_cache = {} # Cache para modelos Whisper carregados

# --- Funções de Ajuda e Utilitários ---

def get_model(model_name: str):
    """Carrega um modelo Whisper em cache ou da memória."""
    if model_name not in whisper_models_cache:
        logger.info(f"Carregando modelo Whisper: {model_name}...")
        config = {"device": DEVICE, "compute_type": COMPUTE_TYPE, "cpu_threads": 0 if DEVICE == "cuda" else max(1, CPU_CORES // 2), "num_workers": 1}
        if DEVICE == "cuda": config["device_index"] = 0
        whisper_models_cache[model_name] = WhisperModel(model_name, **config)
        logger.info("Modelo carregado.")
    return whisper_models_cache[model_name]

async def save_file_stream(file: UploadFile, path: str):
    """Salva um arquivo enviado por streaming, verificando o tamanho."""
    total_size = 0
    with open(path, "wb") as buffer:
        while chunk := await file.read(16384):
            total_size += len(chunk)
            if total_size > MAX_FILE_SIZE:
                os.remove(path)
                raise HTTPException(status_code=413, detail=f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE/(1024*1024):.0f}MB")
            buffer.write(chunk)
    return total_size

def get_ffmpeg_cmd(input_path: str, output_path: str):
    """Gera o comando FFmpeg para extrair e converter áudio."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", "0"]
    # Tenta usar aceleração por hardware se disponível
    if DEVICE == "cuda":
        try:
            subprocess.run(["ffmpeg", "-hwaccels"], capture_output=True, check=True, timeout=5)
            cmd.extend(["-hwaccel", "cuda"])
        except: pass
    cmd.extend(["-i", input_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-y", output_path])
    return cmd

def run_ffmpeg(cmd: List[str], error_msg: str, timeout: int = 300):
    """Executa um comando FFmpeg e lida com erros."""
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail=f"Timeout: {error_msg}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Erro no FFmpeg: {e.stderr}")
        raise HTTPException(status_code=500, detail=f"{error_msg}: {e.stderr}")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="FFmpeg não encontrado. Verifique se está instalado e no PATH do sistema.")

def validate_file(file: UploadFile):
    """Valida a extensão do arquivo enviado."""
    if not file.filename: raise HTTPException(status_code=400, detail="Nome de arquivo não fornecido.")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS: raise HTTPException(status_code=400, detail=f"Formato de arquivo não suportado: {ext}")

def update_status(session_id: str, status: str, step_id: int = 0):
    """Atualiza o status de uma tarefa no cache."""
    status_cache[session_id] = json.dumps({"status": status, "stepId": step_id})

def format_srt_time(seconds: float) -> str:
    """Formata segundos para o padrão de tempo do SRT."""
    h, m, s = int(seconds // 3600), int((seconds % 3600) // 60), int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def create_srt(captions: List[dict], srt_path: str):
    """Cria um arquivo .srt a partir de uma lista de legendas."""
    with open(srt_path, "w", encoding="utf-8") as f:
        for c in captions:
            if not all(key in c for key in ['id', 'start', 'end', 'text']): continue
            text = str(c['text']).replace('\n', ' ').strip()
            if not text: continue
            f.write(f"{c['id']}\n{format_srt_time(float(c['start']))} --> {format_srt_time(float(c['end']))}\n{text}\n\n")

# --- Endpoints da API ---

@app.post("/api/youtube-metadata")
async def get_youtube_metadata(request: YouTubeURLRequest):
    """Extrai metadados de um vídeo do YouTube sem fazer o download completo."""
    url = request.url
    parsed_url = urlparse(url)
    if 'youtube.com' not in parsed_url.netloc and 'youtu.be' not in parsed_url.netloc:
        raise HTTPException(status_code=400, detail="URL inválida. Apenas links do YouTube são permitidos.")

    ydl_opts = {'noplaylist': True, 'quiet': True, 'no_warnings': True}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(executor, lambda: ydl.extract_info(url, download=False))
        
        duration = info.get('duration', 0)
        minutes, seconds = divmod(duration, 60)
        
        metadata = {
            "title": info.get('title', 'Título não disponível'),
            "thumbnail": info.get('thumbnail', ''),
            "duration": duration,
            "duration_formatted": f"{int(minutes):02}:{int(seconds):02}",
            "author": info.get('uploader', 'Autor desconhecido'),
        }
        return JSONResponse(content=metadata)
    except Exception as e:
        logger.error(f"Erro ao buscar metadados do YouTube: {e}")
        raise HTTPException(status_code=500, detail="Falha ao obter metadados do vídeo. Verifique a URL ou tente novamente.")

@app.post("/api/download_youtube")
async def download_youtube_video(request: YouTubeDownloadRequest, background_tasks: BackgroundTasks):
    """Faz o download de um vídeo do YouTube com a qualidade especificada."""
    url, quality = request.url, request.quality
    if 'youtube.com' not in urlparse(url).netloc and 'youtu.be' not in urlparse(url).netloc:
        raise HTTPException(status_code=400, detail="URL inválida.")

    temp_dir = tempfile.mkdtemp()
    background_tasks.add_task(shutil.rmtree, temp_dir)

    format_selector = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    if quality == '720p': format_selector = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    elif quality == '480p': format_selector = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    elif quality == 'audio': format_selector = 'bestaudio/best'

    ydl_opts = {'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'), 'format': format_selector}
    if os.path.exists("cookies.txt"): ydl_opts['cookiefile'] = "cookies.txt"
    if quality == 'audio': ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await asyncio.get_event_loop().run_in_executor(executor, lambda: ydl.download([url]))
        
        files = os.listdir(temp_dir)
        if not files: raise HTTPException(status_code=500, detail="Falha no download.")
        
        file_path = os.path.join(temp_dir, files[0])
        return FileResponse(path=file_path, filename=files[0], media_type='application/octet-stream')
    except Exception as e:
        logger.error(f"Erro no download do YouTube: {e}")
        error_message = str(e).lower()
        if "sign in" in error_message or "age-restricted" in error_message:
            raise HTTPException(status_code=403, detail="Vídeo requer login. Coloque um arquivo 'cookies.txt' válido na raiz do projeto.")
        raise HTTPException(status_code=500, detail=f"Erro no download: {e}")

@app.post("/api/transcribe")
async def transcribe_video(file: UploadFile = File(...), model: str = Form(DEFAULT_MODEL), language: Optional[str] = Form("pt"), session_id: Optional[str] = Form(None)):
    """Transcreve o áudio de um arquivo de vídeo enviado."""
    validate_file(file)
    if model not in WHISPER_MODELS: raise HTTPException(status_code=400, detail=f"Modelo inválido: {model}")
    
    session_id = session_id or str(uuid.uuid4())
    language = language or "pt"
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            update_status(session_id, "Salvando arquivo...", 2)
            temp_video = os.path.join(temp_dir, f"video{Path(file.filename).suffix}")
            file_size = await save_file_stream(file, temp_video)

            update_status(session_id, "Extraindo áudio...", 3)
            temp_audio = os.path.join(temp_dir, "audio.wav")
            run_ffmpeg(get_ffmpeg_cmd(temp_video, temp_audio), "Erro ao extrair áudio")

            update_status(session_id, "Carregando modelo...", 5)
            whisper_model = get_model(model)
            
            update_status(session_id, "Transcrevendo...", 6)
            segments, info = whisper_model.transcribe(temp_audio, language=language, **ULTRA_SPEED_CONFIG)

            captions = [{"id": i + 1, "start": s.start, "end": s.end, "text": s.text.strip()} for i, s in enumerate(segments)]
            
            response = {
                "captions": captions, "language": language, "duration": info.duration,
                "file_size_mb": round(file_size / (1024 * 1024), 2), "session_id": session_id,
            }
            update_status(session_id, "Concluído", 10)
            return JSONResponse(response)
        except Exception as e:
            logger.error(f"Erro na transcrição (sessão {session_id}): {e}")
            update_status(session_id, "Erro", 0)
            if isinstance(e, HTTPException): raise e
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/render")
async def render_video(file: UploadFile = File(...), captions: UploadFile = File(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    """Renderiza legendas em um arquivo de vídeo."""
    validate_file(file)
    if not captions.filename or not captions.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="Legendas devem ser um arquivo JSON.")

    import re
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            temp_video = os.path.join(temp_dir, f"video{Path(file.filename).suffix}")
            await save_file_stream(file, temp_video)

            captions_data = json.loads(await captions.read())
            if not isinstance(captions_data, list): raise ValueError("JSON de legendas inválido.")

            srt_path = os.path.join(temp_dir, "subtitles.srt")
            create_srt(captions_data, srt_path)
            output_video = os.path.join(temp_dir, "output.mp4")
            srt_escaped = srt_path.replace('\\', '/').replace(':', '\\:')
            vf_filter = f"subtitles='{srt_escaped}':force_style='Fontsize=16,Outline=1,Shadow=0.5,BorderStyle=1,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&'"
            render_cmd = ["ffmpeg", "-i", temp_video, "-vf", vf_filter, "-c:a", "copy", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-y", output_video]
            run_ffmpeg(render_cmd, "Erro ao renderizar vídeo", timeout=600)
            if not os.path.exists(output_video): raise HTTPException(status_code=500, detail="Arquivo renderizado não foi criado.")

            # Corrigido: salva o arquivo legendado em FILES_DIR com nome seguro
            safe_filename = re.sub(r'[<>:"/\\|?*]', '_', f"legendado_{Path(file.filename).stem}.mp4")
            persist_path = os.path.join(FILES_DIR, safe_filename)
            shutil.copy2(output_video, persist_path)
            # Opcional: agendar limpeza futura, se desejar
            # background_tasks.add_task(os.remove, persist_path)
            return JSONResponse({"filename": safe_filename, "url": f"/files/{safe_filename}"})
        except Exception as e:
            logger.error(f"Erro na renderização: {e}")
            if isinstance(e, HTTPException): raise e
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/transcribe-status")
async def status_stream(request: Request, session_id: str):
    """Fornece atualizações de status via Server-Sent Events."""
    async def generator():
        last_status = None
        while True:
            if await request.is_disconnected(): break
            status = status_cache.get(session_id)
            if status != last_status and status:
                yield f"data: {status}\n\n"
                last_status = status
            if status and json.loads(status).get("stepId") in [0, 10]:
                status_cache.pop(session_id, None)
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(generator(), media_type="text/event-stream")

@app.get("/api/health")
async def health():
    """Verifica a saúde do sistema."""
    return {"status": "ok"}

@app.get("/api/models")
async def get_available_models():
    """Lista os modelos Whisper disponíveis."""
    recommendations = {"low": ["tiny"], "medium": ["base"], "high": ["small"], "ultra": ["medium"]}
    return {"models": WHISPER_MODELS, "default": DEFAULT_MODEL, "recommended": recommendations.get(HARDWARE_TIER, ["small"])}

@app.get("/api/languages")
async def get_available_languages():
    """Lista os idiomas suportados para transcrição."""
    return {"languages": LANGUAGES, "default": "pt"}

# --- Execução da Aplicação ---
if __name__ == "__main__":
    import uvicorn
    # Altere "main:app" se o seu arquivo for salvo com um nome diferente de 'main.py'
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)