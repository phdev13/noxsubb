import { useState, useEffect } from 'react';
import { Caption, VideoSource } from '../types';

export const useCaptionGenerator = (videoSource: VideoSource | null, videoDuration: number, language: string) => {
    const [captions, setCaptions] = useState<Caption[]>([]);
    const [isLoading, setIsLoading] = useState<boolean>(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!videoSource || videoDuration <= 0) {
            return;
        }

        setIsLoading(true);
        setError(null);
        // Mock: gera legendas de exemplo
        setTimeout(() => {
            setCaptions([
                { id: 1, start: 0, end: 5, text: `Legenda de exemplo em ${language}` },
                { id: 2, start: 5, end: 10, text: `Outra legenda de exemplo em ${language}` }
            ]);
            setIsLoading(false);
        }, 1000);
    }, [videoSource, videoDuration, language]);

    return { captions, isLoading, error, setCaptions };
};