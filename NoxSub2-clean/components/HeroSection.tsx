// ...existing code...
// Substitua todas as comparações:
// youtubeState.status === 'importing'
// por:
// youtubeState.status === ('importing' as YouTubeImportStatus)
// ...existing code...
// Exemplo:
// disabled={youtubeState.status === ('importing' as YouTubeImportStatus)}
// {youtubeState.status === ('importing' as YouTubeImportStatus) && (...)}
// <span className={`... ${youtubeState.status === ('importing' as YouTubeImportStatus) ? 'ml-6' : ''}`}>...</span>
// {youtubeState.status === ('importing' as YouTubeImportStatus) ? 'Importando...' : 'Importar Vídeo'}
// ...existing code...