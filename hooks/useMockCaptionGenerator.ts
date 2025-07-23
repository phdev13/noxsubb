import { useState, useEffect } from 'react';
import { Caption, VideoSource } from '../types';
import { GoogleGenAI, Type, Part } from '@google/genai';

// In a real-world app, you would use a secure way to handle API keys.
// For this project, we assume the API key is available in the execution environment.
const ai = new GoogleGenAI({apiKey: process.env.API_KEY});


/**
 * Extracts a specified number of frames from a video file as base64 strings.
 * @param videoUrl The URL of the video to process.
 * @param duration The total duration of the video.
 * @param numFrames The number of frames to extract.
 * @returns A promise that resolves to an array of base64 encoded frame data (without the data URL prefix).
 */
const extractFrames = async (videoUrl: string, duration: number, numFrames: number): Promise<string[]> => {
    return new Promise((resolve, reject) => {
        const video = document.createElement('video');
        video.src = videoUrl;
        video.crossOrigin = "anonymous";
        video.muted = true; // Mute to avoid playback issues
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d', { willReadFrequently: true });
        const frames: string[] = [];

        if (!context) {
            return reject(new Error("Failed to get canvas context."));
        }

        video.onloadeddata = () => {
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            let framesExtracted = 0;

            const captureFrame = () => {
                // Distribute frames evenly, avoiding the very start and end for better content
                const time = (duration / (numFrames + 1)) * (framesExtracted + 1);
                video.currentTime = time;
            };
            
            video.onseeked = () => {
                if (framesExtracted >= numFrames) return; // Avoid extra seeks
                
                context.drawImage(video, 0, 0, video.videoWidth, video.videoHeight);
                const dataUrl = canvas.toDataURL('image/jpeg').split(',')[1];
                if (dataUrl) {
                   frames.push(dataUrl);
                }
                framesExtracted++;

                if (framesExtracted < numFrames) {
                    captureFrame();
                } else {
                    resolve(frames);
                }
            };

            video.onerror = () => reject(new Error("Failed to load or process video."));

            // Start the process
            captureFrame();
        };

        // Handle cases where video fails to load
        video.load();
    });
};


export const useCaptionGenerator = (videoSource: VideoSource | null, videoDuration: number, language: string) => {
    const [captions, setCaptions] = useState<Caption[]>([]);
    const [isLoading, setIsLoading] = useState<boolean>(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!videoSource || videoDuration <= 0) {
            return;
        }

        const generateCaptions = async () => {
            setIsLoading(true);
            setError(null);
            
            try {
                // 1. Extract more frames for a more detailed analysis
                const frameData = await extractFrames(videoSource.url, videoDuration, 10);

                // 2. Prepare the prompt and image parts for the multimodal request
                const textPart = {
                    text: `You are a world-class AI video transcription service. Your mission is to perform a complete speech-to-text analysis of a video based on a series of frames. The video is ${Math.round(videoDuration)} seconds long. Analyze the provided sequence of 10 frames, infer the context, action, and what is likely being spoken, and generate a COMPLETE and DETAILED transcript for the ENTIRE video. Create many small caption segments to cover the full duration from start to finish. The output must be a JSON array of objects, with each object containing 'id', 'start', 'end', and 'text'. The timestamps must be sequential and not overlap. Generate the transcript in ${language}. Do not describe the scene; transcribe the imagined speech.`
                };

                const imageParts: Part[] = frameData.map(data => ({
                    inlineData: {
                        mimeType: 'image/jpeg',
                        data,
                    }
                }));

                const captionSchema = {
                    type: Type.ARRAY,
                    items: {
                        type: Type.OBJECT,
                        properties: {
                            id: { type: Type.NUMBER, description: "Unique identifier for the caption line." },
                            start: { type: Type.NUMBER, description: "The start time of the caption in seconds." },
                            end: { type: Type.NUMBER, description: "The end time of the caption in seconds." },
                            text: { type: Type.STRING, description: "The text content of the caption." },
                        },
                        required: ['id', 'start', 'end', 'text'],
                    },
                };

                // 3. Call the Gemini API with both text and images
                const response = await ai.models.generateContent({
                    model: 'gemini-2.5-flash',
                    contents: { parts: [textPart, ...imageParts] },
                    config: {
                        responseMimeType: 'application/json',
                        responseSchema: captionSchema,
                    }
                });
                
                const responseText = response.text.trim();
                const parsedCaptions = JSON.parse(responseText);

                if (Array.isArray(parsedCaptions)) {
                    setCaptions(parsedCaptions);
                } else {
                    console.error("API returned a non-array format:", parsedCaptions);
                    throw new Error("API returned an invalid format.");
                }

            } catch (e) {
                console.error("Error generating captions:", e);
                setError("Failed to generate captions. You can still edit them manually.");
                setCaptions([
                    {id: 1, start: 0, end: 5, text: "Start typing your first caption here."},
                ]);
            } finally {
                setIsLoading(false);
            }
        };

        generateCaptions();

    }, [videoSource, videoDuration, language]);

    return { captions, isLoading, error, setCaptions };
};