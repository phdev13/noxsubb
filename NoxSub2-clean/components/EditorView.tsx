// ...existing code...
        } catch (e) {
            const errorMsg = (e instanceof Error ? e.message : String(e));
            console.error('Erro ao baixar vídeo legendado:', e);
            alert(`Erro ao baixar vídeo legendado: ${errorMsg}`);
        } finally {
            setIsDownloading(false);
        }
// ...existing code...