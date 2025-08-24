from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS
import yt_dlp
import os
import uuid
import threading
import time
from pathlib import Path
import shutil

app = Flask(__name__)
CORS(app)

# Configuración
DOWNLOAD_FOLDER = 'downloads'
TEMP_FOLDER = 'temp'

# Crear carpetas si no existen
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)

# Diccionario para almacenar el progreso de las descargas
download_progress = {}

class ProgressHook:
    def __init__(self, download_id):
        self.download_id = download_id
    
    def __call__(self, d):
        if d['status'] == 'downloading':
            try:
                percent = float(d.get('_percent_str', '0%').replace('%', ''))
                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                
                download_progress[self.download_id] = {
                    'status': 'downloading',
                    'percent': percent,
                    'speed': speed,
                    'eta': eta,
                    'stage': 'Descargando audio...'
                }
            except:
                pass
        elif d['status'] == 'finished':
            download_progress[self.download_id] = {
                'status': 'converting',
                'percent': 90,
                'stage': 'Convirtiendo a MP3...'
            }

def get_video_info(url):
    """Obtener información del video sin descargarlo"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'Unknown'),
                'duration': format_duration(info.get('duration', 0)),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
                'thumbnail': info.get('thumbnail', ''),
            }
    except Exception as e:
        raise Exception(f"Error obteniendo información del video: {str(e)}")

def format_duration(seconds):
    """Convertir segundos a formato MM:SS o HH:MM:SS"""
    if not seconds:
        return "0:00"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"

def download_audio(url, download_id):
    """Descargar y convertir video a MP3"""
    try:
        # Actualizar progreso inicial
        download_progress[download_id] = {
            'status': 'starting',
            'percent': 0,
            'stage': 'Iniciando descarga...'
        }
        
        # Configuración de yt-dlp
        output_template = os.path.join(TEMP_FOLDER, f"{download_id}.%(ext)s")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'progress_hooks': [ProgressHook(download_id)],
            'quiet': True,
            'no_warnings': True,
        }
        
        # Descargar video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # El archivo MP3 se guarda con el ID de descarga
            temp_file = os.path.join(TEMP_FOLDER, f"{download_id}.mp3")
            final_file = os.path.join(DOWNLOAD_FOLDER, f"{download_id}.mp3")
            
            # Mover archivo a la carpeta de descargas
            if os.path.exists(temp_file):
                shutil.move(temp_file, final_file)
            
            # Actualizar progreso final
            download_progress[download_id] = {
                'status': 'completed',
                'percent': 100,
                'stage': 'Completado',
                'filename': f"{download_id}.mp3",
                'title': info.get('title', 'Unknown')
            }
            
    except Exception as e:
        download_progress[download_id] = {
            'status': 'error',
            'percent': 0,
            'stage': f'Error: {str(e)}'
        }

@app.route('/')
def index():
    """Servir la página principal"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/video-info', methods=['POST'])
def video_info():
    """Obtener información del video"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL requerida'}), 400
        
        info = get_video_info(url)
        return jsonify({'success': True, 'info': info})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/convert', methods=['POST'])
def convert_video():
    """Iniciar conversión de video a MP3"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL requerida'}), 400
        
        # Generar ID único para la descarga
        download_id = str(uuid.uuid4())
        
        # Iniciar descarga en hilo separado
        thread = threading.Thread(target=download_audio, args=(url, download_id))
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'download_id': download_id})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/progress/<download_id>')
def get_progress(download_id):
    """Obtener progreso de descarga"""
    progress = download_progress.get(download_id, {'status': 'not_found'})
    return jsonify(progress)

@app.route('/api/download/<download_id>')
def download_file(download_id):
    """Descargar archivo MP3"""
    try:
        file_path = os.path.join(DOWNLOAD_FOLDER, f"{download_id}.mp3")
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'Archivo no encontrado'}), 404
        
        # Obtener título del archivo para el nombre de descarga
        progress = download_progress.get(download_id, {})
        title = progress.get('title', 'audio')
        
        # Limpiar título para nombre de archivo
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        filename = f"{safe_title}.mp3"
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='audio/mpeg'
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup/<download_id>', methods=['DELETE'])
def cleanup_file(download_id):
    """Limpiar archivos temporales"""
    try:
        file_path = os.path.join(DOWNLOAD_FOLDER, f"{download_id}.mp3")
        
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Remover del diccionario de progreso
        if download_id in download_progress:
            del download_progress[download_id]
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Limpiar archivos antiguos al iniciar
def cleanup_old_files():
    """Limpiar archivos más antiguos de 1 hora"""
    try:
        current_time = time.time()
        for filename in os.listdir(DOWNLOAD_FOLDER):
            file_path = os.path.join(DOWNLOAD_FOLDER, filename)
            if os.path.getctime(file_path) < current_time - 3600:  # 1 hora
                os.remove(file_path)
                print(f"Archivo eliminado: {filename}")
    except Exception as e:
        print(f"Error limpiando archivos: {e}")

# Template HTML integrado
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube a MP3 Converter - Funcional</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 600px;
            text-align: center;
            animation: fadeIn 0.8s ease-out;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .logo {
            font-size: 3em;
            margin-bottom: 10px;
            background: linear-gradient(45deg, #FF0000, #FF4444);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        h1 {
            color: #333;
            margin-bottom: 30px;
            font-size: 1.8em;
            font-weight: 300;
        }

        .input-group {
            margin-bottom: 30px;
            position: relative;
        }

        .url-input {
            width: 100%;
            padding: 18px 50px 18px 20px;
            border: 2px solid #e0e0e0;
            border-radius: 15px;
            font-size: 16px;
            transition: all 0.3s ease;
            background: rgba(255, 255, 255, 0.9);
        }

        .url-input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 20px rgba(102, 126, 234, 0.2);
            transform: translateY(-2px);
        }

        .paste-btn {
            position: absolute;
            right: 15px;
            top: 50%;
            transform: translateY(-50%);
            background: #667eea;
            color: white;
            border: none;
            padding: 8px 15px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.3s ease;
        }

        .paste-btn:hover {
            background: #5a6fd8;
            transform: translateY(-50%) scale(1.05);
        }

        .convert-btn {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 18px 40px;
            border-radius: 15px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin: 10px;
            min-width: 200px;
        }

        .convert-btn:hover:not(:disabled) {
            transform: translateY(-3px);
            box-shadow: 0 15px 35px rgba(102, 126, 234, 0.4);
        }

        .convert-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        .progress-container {
            margin: 30px 0;
            opacity: 0;
            transition: opacity 0.3s ease;
        }

        .progress-container.show {
            opacity: 1;
        }

        .progress-bar {
            width: 100%;
            height: 8px;
            background: rgba(102, 126, 234, 0.2);
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 15px;
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            width: 0%;
            transition: width 0.3s ease;
            border-radius: 4px;
        }

        .status-text {
            color: #666;
            font-size: 14px;
            margin-bottom: 10px;
        }

        .video-info {
            background: rgba(255, 255, 255, 0.8);
            border-radius: 15px;
            padding: 20px;
            margin: 20px 0;
            text-align: left;
            display: none;
            animation: slideIn 0.5s ease-out;
        }

        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-20px); }
            to { opacity: 1; transform: translateX(0); }
        }

        .video-title {
            font-weight: 600;
            color: #333;
            margin-bottom: 10px;
            font-size: 16px;
        }

        .video-details {
            color: #666;
            font-size: 14px;
            line-height: 1.4;
        }

        .download-link {
            display: inline-block;
            background: #28a745;
            color: white;
            padding: 12px 25px;
            border-radius: 10px;
            text-decoration: none;
            margin-top: 15px;
            transition: all 0.3s ease;
            font-weight: 500;
            text-align: center;
        }

        .download-link:hover {
            background: #218838;
            transform: translateY(-2px);
        }

        .error-message, .success-message {
            padding: 15px;
            border-radius: 10px;
            margin: 20px 0;
            display: none;
        }

        .error-message {
            background: rgba(220, 53, 69, 0.1);
            color: #dc3545;
            border-left: 4px solid #dc3545;
        }

        .success-message {
            background: rgba(40, 167, 69, 0.1);
            color: #28a745;
            border-left: 4px solid #28a745;
        }

        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid #ffffff40;
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 1s ease-in-out infinite;
            margin-right: 10px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        @media (max-width: 600px) {
            .container {
                padding: 30px 20px;
                margin: 10px;
            }
            
            .logo {
                font-size: 2em;
            }
            
            h1 {
                font-size: 1.5em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🎵</div>
        <h1>YouTube a MP3 Converter</h1>
        <p style="color: #666; margin-bottom: 30px;">Convierte videos de YouTube a archivos MP3 de alta calidad</p>
        
        <div class="input-group">
            <input type="text" 
                   class="url-input" 
                   id="videoUrl" 
                   placeholder="Pega aquí la URL del video de YouTube..."
                   autocomplete="off">
            <button class="paste-btn" onclick="pasteFromClipboard()">📋 Pegar</button>
        </div>
        
        <button class="convert-btn" onclick="convertVideo()">
            <span id="btn-text">🔄 Convertir a MP3</span>
        </button>
        
        <div class="progress-container" id="progressContainer">
            <div class="status-text" id="statusText">Preparando descarga...</div>
            <div class="progress-bar">
                <div class="progress-fill" id="progressFill"></div>
            </div>
        </div>
        
        <div class="video-info" id="videoInfo">
            <div class="video-title" id="videoTitle"></div>
            <div class="video-details" id="videoDetails"></div>
            <a href="#" class="download-link" id="downloadLink" target="_blank">
                📥 Descargar MP3
            </a>
        </div>
        
        <div class="error-message" id="errorMessage"></div>
        <div class="success-message" id="successMessage"></div>
    </div>

    <script>
        let isConverting = false;
        let currentDownloadId = null;
        
        async function pasteFromClipboard() {
            try {
                const text = await navigator.clipboard.readText();
                document.getElementById('videoUrl').value = text;
            } catch (err) {
                console.log('No se pudo acceder al portapapeles');
            }
        }
        
        async function convertVideo() {
            if (isConverting) return;
            
            const url = document.getElementById('videoUrl').value.trim();
            const urlPattern = /^(https?:\/\/)?(www\.)?(youtube\.com\/(watch\?v=|embed\/)|youtu\.be\/)[\w\-]+/;
            
            hideMessages();
            
            if (!url) {
                showError('Por favor, ingresa una URL de YouTube');
                return;
            }
            
            if (!urlPattern.test(url)) {
                showError('Por favor, ingresa una URL válida de YouTube');
                return;
            }
            
            try {
                // Primero obtener información del video
                const infoResponse = await fetch('/api/video-info', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({url: url})
                });
                
                const infoData = await infoResponse.json();
                
                if (!infoData.success) {
                    throw new Error(infoData.error);
                }
                
                showVideoInfo(infoData.info);
                
                // Iniciar conversión
                startConversion();
                
                const response = await fetch('/api/convert', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({url: url})
                });
                
                const data = await response.json();
                
                if (!data.success) {
                    throw new Error(data.error);
                }
                
                currentDownloadId = data.download_id;
                monitorProgress(currentDownloadId);
                
            } catch (error) {
                showError('Error: ' + error.message);
                stopConversion();
            }
        }
        
        async function monitorProgress(downloadId) {
            const checkProgress = async () => {
                try {
                    const response = await fetch(`/api/progress/${downloadId}`);
                    const progress = await response.json();
                    
                    if (progress.status === 'not_found') {
                        showError('Descarga no encontrada');
                        stopConversion();
                        return;
                    }
                    
                    updateStatus(progress.stage || 'Procesando...', progress.percent || 0);
                    
                    if (progress.status === 'completed') {
                        showDownloadLink(downloadId);
                        showSuccess('¡Conversión completada exitosamente!');
                        stopConversion();
                    } else if (progress.status === 'error') {
                        showError(progress.stage || 'Error durante la conversión');
                        stopConversion();
                    } else {
                        setTimeout(checkProgress, 1000);
                    }
                } catch (error) {
                    showError('Error monitoreando progreso: ' + error.message);
                    stopConversion();
                }
            };
            
            checkProgress();
        }
        
        function startConversion() {
            isConverting = true;
            const btn = document.querySelector('.convert-btn');
            const btnText = document.getElementById('btn-text');
            
            btn.disabled = true;
            btnText.innerHTML = '<span class="spinner"></span>Convirtiendo...';
            
            const progressContainer = document.getElementById('progressContainer');
            progressContainer.classList.add('show');
        }
        
        function stopConversion() {
            isConverting = false;
            const btn = document.querySelector('.convert-btn');
            const btnText = document.getElementById('btn-text');
            
            btn.disabled = false;
            btnText.innerHTML = '🔄 Convertir a MP3';
            
            setTimeout(() => {
                const progressContainer = document.getElementById('progressContainer');
                progressContainer.classList.remove('show');
            }, 2000);
        }
        
        function updateStatus(text, progress) {
            document.getElementById('statusText').textContent = text;
            document.getElementById('progressFill').style.width = progress + '%';
        }
        
        function showVideoInfo(info) {
            const videoInfoDiv = document.getElementById('videoInfo');
            const videoTitle = document.getElementById('videoTitle');
            const videoDetails = document.getElementById('videoDetails');
            
            videoTitle.textContent = info.title;
            videoDetails.innerHTML = `
                <strong>Canal:</strong> ${info.uploader}<br>
                <strong>Duración:</strong> ${info.duration}<br>
                <strong>Vistas:</strong> ${info.view_count?.toLocaleString() || 'N/A'}
            `;
            
            videoInfoDiv.style.display = 'block';
        }
        
        function showDownloadLink(downloadId) {
            const downloadLink = document.getElementById('downloadLink');
            downloadLink.href = `/api/download/${downloadId}`;
            downloadLink.style.display = 'inline-block';
        }
        
        function showError(message) {
            const errorDiv = document.getElementById('errorMessage');
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
        }
        
        function showSuccess(message) {
            const successDiv = document.getElementById('successMessage');
            successDiv.textContent = message;
            successDiv.style.display = 'block';
        }
        
        function hideMessages() {
            document.getElementById('errorMessage').style.display = 'none';
            document.getElementById('successMessage').style.display = 'none';
        }
        
        document.getElementById('videoUrl').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                convertVideo();
            }
        });
        
        document.getElementById('videoUrl').addEventListener('input', function() {
            hideMessages();
            document.getElementById('videoInfo').style.display = 'none';
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    print("🎵 YouTube to MP3 Converter iniciando...")
    print("📂 Limpiando archivos antiguos...")
    cleanup_old_files()
    
    # Obtener puerto del entorno (para deployment) o usar 5000 por defecto
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    
    print(f"🚀 Servidor iniciado en puerto {port}")
    print("💡 Presiona Ctrl+C para detener")
    
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
