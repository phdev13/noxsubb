import requests
import json

# Caminho do vídeo para teste
VIDEO_PATH = 'video_teste.mp4'  # coloque um vídeo pequeno para teste
API_URL = 'http://localhost:8000/api/transcribe'

# Testa transcrição
try:
    with open(VIDEO_PATH, 'rb') as f:
        files = {'file': f}
        print('Enviando vídeo para transcrição...')
        resp = requests.post(API_URL, files=files)
        print('Status:', resp.status_code)
        if resp.ok:
            captions = resp.json()
            print('Legendas geradas:', json.dumps(captions, ensure_ascii=False, indent=2))
            # Salva para teste do render
            with open('captions_test.json', 'w', encoding='utf-8') as out:
                json.dump(captions, out, ensure_ascii=False)
        else:
            print('Erro detalhado:', resp.text)
except Exception as e:
    print('Erro ao enviar vídeo:', e)

# Testa renderização
try:
    API_RENDER = 'http://localhost:8000/api/render'
    with open(VIDEO_PATH, 'rb') as fvid, open('captions_test.json', 'rb') as fcapt:
        files = {'file': fvid, 'captions': fcapt}
        print('Enviando vídeo e legendas para renderização...')
        resp = requests.post(API_RENDER, files=files)
        print('Status:', resp.status_code)
        if resp.ok:
            with open('video_legendado.mp4', 'wb') as fout:
                fout.write(resp.content)
            print('Vídeo legendado salvo como video_legendado.mp4')
        else:
            print('Erro detalhado:', resp.text)
except Exception as e:
    print('Erro ao renderizar vídeo:', e)
