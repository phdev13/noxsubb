import os
import subprocess

# Caminho do seu projeto
repo_path = r"C:\Users\Philippe\Desktop\NoxSub - Funcionando - Copia - Copia - Copia"

# URL do repositório remoto
remote_url = "https://github.com/noxsubph1313/NoxSub---Funcionando.git"

# Configurações do git (se quiser configurar localmente)
git_user_name = "Philippe"
git_user_email = "noxsubph13@gmail.com"

def run_command(command, cwd=None):
    """Executa um comando no shell e mostra o output"""
    result = subprocess.run(command, cwd=cwd, shell=True, text=True, capture_output=True)
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"Erro ao executar comando: {command}")
        print(result.stderr)
    return result.returncode == 0

def main():
    # Vai para a pasta do projeto
    if not os.path.isdir(repo_path):
        print(f"Pasta {repo_path} não existe.")
        return

    print(f"Entrando na pasta do repositório: {repo_path}")

    # Configurar usuário e email do git local (opcional)
    run_command(f'git config user.name "{git_user_name}"', cwd=repo_path)
    run_command(f'git config user.email "{git_user_email}"', cwd=repo_path)

    # Inicializar git (se já tiver, apenas informa)
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        print("Inicializando repositório git...")
        if not run_command("git init", cwd=repo_path):
            return
    else:
        print("Repositório git já inicializado.")

    # Adicionar remote origin, se não existir
    remotes = subprocess.run("git remote", cwd=repo_path, shell=True, text=True, capture_output=True)
    if "origin" not in remotes.stdout:
        print("Adicionando remote origin...")
        if not run_command(f"git remote add origin {remote_url}", cwd=repo_path):
            return
    else:
        print("Remote origin já configurado.")

    # Adicionar todos os arquivos
    print("Adicionando arquivos ao stage...")
    if not run_command("git add .", cwd=repo_path):
        return

    # Commit
    commit_message = "Atualização automática via script"
    print(f"Fazendo commit com a mensagem: {commit_message}")
    if not run_command(f'git commit -m "{commit_message}"', cwd=repo_path):
        print("Nada para commitar ou erro no commit.")

    # Push para o branch main (pode ser master, dependendo do seu repositório)
    print("Enviando alterações para o GitHub (branch main)...")
    if not run_command("git push -u origin main", cwd=repo_path):
        print("Erro ao fazer push. Verifique se o branch main existe ou suas credenciais.")

if __name__ == "__main__":
    main()
