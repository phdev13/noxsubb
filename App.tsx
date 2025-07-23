
import React, { useState, useCallback } from 'react';
import HeroSection from './components/HeroSection';
import EditorView from './components/EditorView';
import { VideoSource } from './types';
import { LogoIcon } from './components/icons';

type View = 'upload' | 'editing';

const App: React.FC = () => {
  const [view, setView] = useState<View>('upload');
  const [videoSource, setVideoSource] = useState<VideoSource | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleVideoSelect = useCallback((file: File) => {
    if (file.type.startsWith('video/')) {
      const url = URL.createObjectURL(file);
      setVideoSource({ url, filename: file.name });
      setView('editing');
      setError(null);
    } else {
      setError('Invalid file type. Please upload a video file.');
    }
  }, []);

  const handleBackToUpload = useCallback(() => {
    if (videoSource) {
      URL.revokeObjectURL(videoSource.url);
    }
    setView('upload');
    setVideoSource(null);
    setError(null);
  }, [videoSource]);

  return (
    <div className="min-h-screen text-gray-200 flex flex-col items-center p-4 sm:p-6 lg:p-8">
      <header className="w-full max-w-7xl mb-8 flex items-center justify-between">
         <div className="flex items-center gap-3">
          <LogoIcon className="h-8 w-8 text-purple-400" />
          <h1 className="text-2xl font-bold tracking-tight text-white">NoxSub</h1>
        </div>
        {view === 'editing' && (
           <button 
             onClick={handleBackToUpload}
             className="bg-slate-700 hover:bg-slate-600 text-white font-semibold py-2 px-4 rounded-lg transition-colors duration-200"
           >
             New Project
           </button>
        )}
      </header>
      <main className="w-full flex-grow flex items-start justify-center">
        {view === 'upload' ? (
          <HeroSection onVideoSelect={handleVideoSelect} error={error} />
        ) : videoSource ? (
          <EditorView videoSource={videoSource} />
        ) : null}
      </main>
    </div>
  );
};

export default App;