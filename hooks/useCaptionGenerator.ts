import { useState, useEffect, useRef } from 'react';
import { Caption, VideoSource } from '../types';

async function getBackendPort(): Promise<number> {
    return 8000; // Porta fixa para backend
}

// Função para testar se o backend está disponível
async function testBackendConnection(port: number): Promise<boolean> {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 segundos timeout

        // Usa o backendPort dinâmico
        const response = await fetch(`http://localhost:${port}/api/health`, {
            method: 'GET',
            mode: 'cors',
            credentials: 'omit',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            signal: controller.signal
        });

        clearTimeout(timeoutId);
        return response.ok || response.status === 200;
    } catch (error) {
        console.warn(`Backend na porta ${port} não está disponível:`, error);
        if (error instanceof TypeError && error.message.includes('CORS')) {
            console.info('Servidor pode estar rodando mas com problema de CORS');
            return true;
        }
        return false;
    }
}

export const useCaptionGenerator = (
    videoSource: VideoSource | null,
    videoDuration: number,
    language: string,
    model: string = 'small',
    shouldGenerate: boolean = false
) => {
    const [captions, setCaptions] = useState<Caption[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [loadingText, setLoadingText] = useState('');
    const [elapsed, setElapsed] = useState(0);
    const [stepId, setStepId] = useState<string | number | null>(null);

    const timerRef = useRef<NodeJS.Timeout | null>(null);
    const eventSourceRef = useRef<EventSource | null>(null);
    const abortControllerRef = useRef<AbortController | null>(null);

    const cleanup = () => {
        if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
        }

        if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
        }

        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
        }
    };

    const cancelTranscription = () => {
        cleanup();
        setIsLoading(false);
        setLoadingText('Transcrição cancelada');
        setElapsed(0);
        setError(null);
        setStepId(null);
    };

    useEffect(() => {
        if (!videoSource || videoDuration <= 0 || !shouldGenerate) return;

        const generateCaptions = async () => {
            setIsLoading(true);
            setError(null);
            setElapsed(0);
            setLoadingText('Verificando conexão com o servidor...');
            setStepId(null);

            // Criar novo AbortController para esta requisição
            abortControllerRef.current = new AbortController();

            try {
                const backendPort = await getBackendPort();

                // Testar conexão com o backend antes de prosseguir
                setLoadingText('Verificando servidor backend...');
                const isBackendAvailable = await testBackendConnection(backendPort);
                if (!isBackendAvailable) {
                    throw new Error(`Não foi possível conectar ao servidor backend na porta ${backendPort}. ` +
                        'Possíveis problemas:\n' +
                        '1. Servidor não está rodando\n' +
                        '2. Problema de CORS - verifique a configuração do servidor\n' +
                        '3. Porta bloqueada por firewall');
                }

                setLoadingText('Baixando vídeo...');

                // Download do vídeo com timeout
                const videoResponse = await fetch(videoSource.url, {
                    signal: abortControllerRef.current.signal
                });

                if (!videoResponse.ok) {
                    throw new Error(`Não foi possível baixar o vídeo. Status: ${videoResponse.status}`);
                }

                const blob = await videoResponse.blob();
                const file = new File([blob], videoSource.filename || 'video.mp4', { type: blob.type });
                const sessionId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

                setLoadingText('Preparando transcrição...');

                const formData = new FormData();
                formData.append('file', file);
                formData.append('model', model);
                formData.append('language', language);
                formData.append('session_id', sessionId);

                // Iniciar timer
                timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000);

                // Configurar EventSource para status updates
                try {
                    eventSourceRef.current = new EventSource(
                        `http://localhost:${backendPort}/api/transcribe-status?session_id=${sessionId}`
                    );

                    eventSourceRef.current.onmessage = (e) => {
                        try {
                            const data = JSON.parse(e.data);
                            setLoadingText(data.status || 'Processando...');
                            setStepId(data.stepId || null);
                        } catch {
                            setLoadingText(e.data || 'Processando...');
                            setStepId(null);
                        }
                    };

                    eventSourceRef.current.onerror = (error) => {
                        console.warn('EventSource error:', error);
                        eventSourceRef.current?.close();
                    };
                } catch (sseError) {
                    console.warn('Não foi possível estabelecer conexão de status em tempo real:', sseError);
                    setLoadingText('Processando transcrição...');
                }

                // Fazer a requisição de transcrição
                setLoadingText('Enviando vídeo para transcrição...');
                const backendResponse = await fetch(`http://localhost:${backendPort}/api/transcribe`, {
                    method: 'POST',
                    body: formData,
                    mode: 'cors',
                    credentials: 'omit',
                    signal: abortControllerRef.current.signal,
                });

                if (!backendResponse.ok) {
                    const errorText = await backendResponse.text();
                    throw new Error(`Erro do servidor (${backendResponse.status}): ${errorText}`);
                }

                const responseJson = await backendResponse.json();
                const parsedCaptions = responseJson.captions || responseJson;

                if (Array.isArray(parsedCaptions) && parsedCaptions.length > 0) {
                    setCaptions(parsedCaptions);
                    setLoadingText('Transcrição concluída!');
                } else {
                    console.warn('Nenhuma legenda foi gerada, criando legenda padrão');
                    setCaptions([{
                        id: 1,
                        start: 0,
                        end: Math.min(5, videoDuration),
                        text: "Digite sua primeira legenda aqui."
                    }]);
                    setLoadingText('Transcrição não gerou resultados');
                }

            } catch (e: any) {
                console.error("Erro ao gerar legendas:", e);

                let errorMsg = 'Erro desconhecido';

                if (e.name === 'AbortError') {
                    errorMsg = 'Operação cancelada pelo usuário';
                } else if (e.name === 'TypeError' && (e.message.includes('Failed to fetch') || e.message.includes('CORS'))) {
                    errorMsg = 'Erro de conectividade ou CORS. Verifique se:\n' +
                        '1. O backend está rodando na porta correta\n' +
                        '2. O servidor backend permite requisições CORS\n' +
                        '3. Não há bloqueio de firewall';
                } else if (e.message.includes('não está rodando') || e.message.includes('não foi possível conectar')) {
                    errorMsg = e.message;
                } else {
                    errorMsg = e.message || String(e);
                }

                setError(`Falha ao gerar legendas: ${errorMsg}`);

                // Criar legenda padrão apenas se não foi cancelado
                if (e.name !== 'AbortError') {
                    setCaptions([{
                        id: 1,
                        start: 0,
                        end: Math.min(5, videoDuration),
                        text: "Digite sua primeira legenda aqui."
                    }]);
                }
            } finally {
                if (abortControllerRef.current && !abortControllerRef.current.signal.aborted) {
                    setIsLoading(false);
                    if (!error) {
                        setLoadingText('');
                    }
                    setStepId(null);
                }
                cleanup();
            }
        };

        generateCaptions();
        return cleanup;
    }, [videoSource, videoDuration, language, model, shouldGenerate]);

    const downloadRenderedVideo = async (quality: 'low' | 'medium' | 'high' = 'medium') => {
        try {
            if (!videoSource || captions.length === 0) {
                throw new Error('Vídeo ou legendas não disponíveis.');
            }

            const backendPort = await getBackendPort();

            // Testar conexão antes de prosseguir
            const isBackendAvailable = await testBackendConnection(backendPort);
            if (!isBackendAvailable) {
                throw new Error(`Servidor backend não está disponível na porta ${backendPort}.`);
            }

            const response = await fetch(videoSource.url);
            if (!response.ok) {
                throw new Error(`Não foi possível baixar o vídeo. Status: ${response.status}`);
            }

            const blob = await response.blob();
            const file = new File([blob], videoSource.filename || 'video.mp4', { type: blob.type });
            const captionsFile = new File([JSON.stringify(captions, null, 2)], 'captions.json', {
                type: 'application/json'
            });

            const formData = new FormData();
            formData.append('file', file);
            formData.append('captions', captionsFile);
            formData.append('quality', quality);

            const backendResponse = await fetch(`http://localhost:${backendPort}/api/render`, {
                method: 'POST',
                body: formData,
                mode: 'cors',
                credentials: 'omit',
            });

            if (!backendResponse.ok) {
                const errorText = await backendResponse.text();
                throw new Error(`Erro do servidor (${backendResponse.status}): ${errorText}`);
            }

            // Recebe o nome do arquivo gerado
            const json = await backendResponse.json();
            const filename = json.filename;
            if (!filename) throw new Error('Arquivo legendado não gerado.');
            const fileUrl = `http://localhost:${backendPort}/files/${filename}`;

            // Faz o download via GET
            const fileResponse = await fetch(fileUrl);
            if (!fileResponse.ok) throw new Error('Falha ao baixar o arquivo legendado.');
            const videoBlob = await fileResponse.blob();
            const url = URL.createObjectURL(videoBlob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);

        } catch (e: any) {
            const errorMsg = e.message || String(e);
            console.error('Erro ao baixar vídeo legendado:', e);
            alert(`Erro ao baixar vídeo legendado: ${errorMsg}`);
        }
    };

    return {
        captions,
        isLoading,
        error,
        setCaptions,
        downloadRenderedVideo,
        loadingText,
        elapsed,
        cancelTranscription,
        stepId
    };
};